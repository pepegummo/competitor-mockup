"""ข้อมูลจากเว็บตลาดหลักทรัพย์ฯ (set.or.th): ข่าวแจ้งตลาด และงบการเงินที่บริษัทยื่น

ใช้ API ภายในของหน้าเว็บ (ไม่ได้เปิดให้ใช้อย่างเป็นทางการ) ต้องเปิดหน้าแรกก่อนเพื่อรับ cookie
ไม่งั้นจะได้ 403 ถ้าวันหลังใช้ไม่ได้จะ raise SourceSkipped แทนการทำให้แอปพัง
ใช้งานจริงควรเปลี่ยนไปใช้ SETSMART (บริการแบบเสียเงินของ SET)
"""
from datetime import date, timedelta

import requests

from core.sources import SourceSkipped, item

BASE = "https://www.set.or.th"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Referer": f"{BASE}/th/home",
}
_session = None
_stock_list = None


def _warm():
    global _session
    _session = requests.Session()
    _session.headers.update(HEADERS)
    _session.get(f"{BASE}/th/home", timeout=20)


def _get(path, **params):
    try:
        if _session is None:
            _warm()
        r = _session.get(BASE + path, params=params, timeout=20)
        if r.status_code == 403:  # cookie หมดอายุ ลองรับใหม่ 1 ครั้ง
            _warm()
            r = _session.get(BASE + path, params=params, timeout=20)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            raise SourceSkipped("ไม่พบชื่อหุ้นนี้บน SET (ตรวจชื่อหุ้นในการตั้งค่าแหล่งข้อมูล)")
        raise SourceSkipped(f"SET API ใช้ไม่ได้ตอนนี้ (HTTP {e.response.status_code})")
    except (requests.RequestException, ValueError) as e:
        raise SourceSkipped(f"SET API ใช้ไม่ได้ตอนนี้ ({type(e).__name__})")


def stock_list():
    """{ชื่อหุ้น: {nameTH, nameEN}} ของหลักทรัพย์ทั้งหมด (โหลดครั้งเดียวต่อ process)"""
    global _stock_list
    if _stock_list is None:
        _stock_list = {s["symbol"]: {"nameTH": s.get("nameTH", ""), "nameEN": s.get("nameEN", "")}
                       for s in _get("/api/set/stock/list").get("securitySymbols", [])}
    return _stock_list


def _symbol(company):
    symbol = (company.get("set_symbol") or "").strip().upper()
    if not symbol:
        raise SourceSkipped("ยังไม่ได้ใส่ชื่อหุ้น SET")
    return symbol


# ---------- ข่าวแจ้งตลาด ----------

def fetch(company, limit=20):
    """ข่าวที่บริษัทแจ้งตลาดย้อนหลัง 90 วัน (ประกาศงบ แต่งตั้งกรรมการ ซื้อกิจการ ฯลฯ) ใหม่สุดก่อน"""
    symbol = _symbol(company)
    today = date.today()
    data = _get("/api/set/news/search", symbol=symbol, lang="th",
                fromDate=(today - timedelta(days=90)).strftime("%d/%m/%Y"), toDate=today.strftime("%d/%m/%Y"))
    news = sorted(data.get("newsInfoList") or [], key=lambda n: n.get("datetime", ""), reverse=True)
    return [item("set", "SET", n["headline"], n["url"], n.get("datetime", "")) for n in news[:limit]]


# ---------- งบการเงิน ----------

# ชื่อบัญชีในงบกำไรขาดทุนแบบย่อของ SET (จับจากชื่อ เพราะรหัสบัญชีต่างกันตามประเภทธุรกิจ)
ACCOUNTS = {"revenue": "รวมรายได้", "ebitda": "EBITDA", "net_profit": "กำไร(ขาดทุน)สุทธิ", "eps": "กำไรต่อหุ้น"}


def _accounts(statement):
    out = {}
    for a in statement.get("accounts", []):
        name = a["accountName"].replace(" ", "")
        for key, prefix in ACCOUNTS.items():
            if key not in out and name.startswith(prefix.replace(" ", "")) and a["amount"] is not None:
                # หน่วยในงบคือพันบาท (divider 1000) แปลงเป็นล้านบาท ยกเว้น EPS ที่เป็นบาท
                out[key] = a["amount"] * a["divider"] / 1e6 if a["divider"] != 1 else a["amount"]
    return out


def _period(statement):
    q = statement["quarter"]
    return f"{'ทั้งปี' if q == 'Q9' else q}/{statement['year']}"


def _million(v):
    return round(v / 1000, 2) if v is not None else None  # financial-data เป็นพันบาท


def financials(symbol):
    """งบรวมของรอบล่าสุดเทียบช่วงเดียวกันปีก่อน + งบย้อนหลังรายปี + ข้อมูลตลาด (ตัวเงินเป็นล้านบาท)"""
    symbol = symbol.strip().upper()
    statements = []
    for year in (date.today().year, date.today().year - 1):  # ต้นปีอาจยังไม่มีงบของปีนี้
        statements = [s for s in _get(f"/api/set/factsheet/{symbol}/financialstatement", language="th",
                                      financialStatementType="Q", accountType="I", fiscalYear=year) or []
                      if s.get("fsType") == "C"] or statements
        if statements:
            break
    if not statements:
        raise SourceSkipped(f"ไม่พบงบการเงินของ {symbol} บน SET")
    latest = statements[0]
    prev = next((s for s in statements[1:]
                 if s["quarter"] == latest["quarter"] and s["year"] == latest["year"] - 1), None)

    history = [{
        "year": h["year"], "period": "ทั้งปี" if h["quarter"] == "Q9" else h["quarter"],
        "end_date": (h.get("endDate") or "")[:10],
        "revenue": _million(h.get("totalRevenue")), "net_profit": _million(h.get("netProfit")),
        "net_margin": h.get("netProfitMargin"), "roe": h.get("roe"), "de_ratio": h.get("deRatio"),
    } for h in _get(f"/api/set/stock/{symbol}/company-highlight/financial-data", lang="th") or []]

    market = _get(f"/api/set/stock/{symbol}/highlight-data", lang="th") or {}
    return {
        "symbol": symbol,
        "latest": {"period": _period(latest), "end_date": latest["endDate"][:10], "status": latest.get("status"),
                   "filed_url": latest.get("downloadUrl"), **_accounts(latest)},
        "previous": ({"period": _period(prev), **_accounts(prev)} if prev else None),
        "history": history,
        "market": {"market_cap": round(market["marketCap"] / 1e6) if market.get("marketCap") else None,  # บาท
                   "pe": market.get("peRatio"), "dividend_yield": market.get("dividendYield"),
                   "as_of": (market.get("asOfDate") or "")[:10]},
    }
