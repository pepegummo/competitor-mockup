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
    """{ชื่อหุ้น: {nameTH, nameEN, type, market, industry, sector}} ของหลักทรัพย์ทั้งหมด รวมใบสำคัญแสดงสิทธิ DR ETF
    (โหลดครั้งเดียวต่อ process)"""
    global _stock_list
    if _stock_list is not None:
        return _stock_list
    from core import db  # เก็บไว้ใน DB 1 วัน: เปิดแอปเร็วขึ้น และใช้ได้แม้ไม่มีเน็ต (โหมดเดโม)
    fresh = db.get_cache(["stocklist"], max_age_hours=24).get("stocklist")
    if fresh:
        _stock_list = fresh
        return _stock_list
    try:
        _stock_list = {s["symbol"]: {"nameTH": s.get("nameTH", ""), "nameEN": s.get("nameEN", ""),
                                     "type": s.get("securityType", ""), "market": s.get("market", ""),
                                     "industry": s.get("industry", ""), "sector": s.get("sector", "")}
                       for s in _get("/api/set/stock/list").get("securitySymbols", [])}
    except SourceSkipped:
        stale = db.get_cache(["stocklist"]).get("stocklist")  # SET ใช้ไม่ได้: ใช้ของเก่าที่เก็บไว้
        if not stale:
            raise
        _stock_list = stale
        return _stock_list
    db.set_cache("stocklist", _stock_list)
    return _stock_list


def listed_companies():
    """เฉพาะหุ้นสามัญของบริษัทใน SET และ mai (~930 ตัว) ใช้เป็นรายชื่อให้เลือก"""
    return {k: v for k, v in stock_list().items() if v["type"] == "S"}


def peers(symbol):
    """หุ้นทุกตัวในหมวดธุรกิจเดียวกัน คืน (รหัสหมวด, [ชื่อหุ้น]) · หุ้นใน mai ไม่มี sector ใช้ industry ใน mai แทน"""
    listed = listed_companies()
    me = listed.get(symbol.strip().upper())
    if not me:
        raise SourceSkipped(f"ไม่พบ {symbol} ในรายชื่อหุ้นสามัญของ SET")
    if me["sector"]:
        return me["sector"], [k for k, v in listed.items() if v["sector"] == me["sector"]]
    return (f"{me['market']}-{me['industry']}",
            [k for k, v in listed.items() if not v["sector"] and v["market"] == me["market"]
             and v["industry"] == me["industry"]])


def _growth(cur, prev):
    if cur is None or not prev or prev <= 0:
        return None
    return round((cur - prev) / prev * 100, 1)


def highlight(symbol):
    """ตัวเลขสรุปของ 1 หุ้น (2 call) ใช้เทียบทั้งหมวด: งบทั้งปีล่าสุดเทียบปีก่อน + มูลค่าตลาด P/E P/BV ปันผล
    ใช้เฉพาะงบทั้งปี (แถวสุดท้ายมักเป็นงบสะสม 6M/9M ซึ่งเทียบกับทั้งปีไม่ได้) · ตัวเงินล้านบาท"""
    symbol = symbol.strip().upper()
    rows = _get(f"/api/set/stock/{symbol}/company-highlight/financial-data", lang="th") or []
    market = _get(f"/api/set/stock/{symbol}/highlight-data", lang="th") or {}
    years = [r for r in rows if r.get("quarter") == "Q9"]
    last = years[-1] if years else {}
    prev = years[-2] if len(years) > 1 else {}
    return {
        "symbol": symbol,
        "period": f"ทั้งปี {last['year']}" if last else None,
        "fy_end": (last.get("endDate") or "")[:10],
        "revenue_mb": _million(last.get("totalRevenue")),
        "net_profit_mb": _million(last.get("netProfit")),
        "revenue_yoy_pct": _growth(last.get("totalRevenue"), prev.get("totalRevenue")),
        "net_profit_yoy_pct": _growth(last.get("netProfit"), prev.get("netProfit")),
        "net_margin_pct": last.get("netProfitMargin"),
        "roe_pct": last.get("roe"),
        "de_ratio": last.get("deRatio"),
        "market_cap_mb": round(market["marketCap"] / 1e6) if market.get("marketCap") else None,
        "pe": market.get("peRatio"),
        "pbv": market.get("pbRatio"),
        "dividend_yield_pct": market.get("dividendYield"),
        "as_of": (market.get("asOfDate") or "")[:10],
    }


def price_history(symbol, period="3M"):
    """ราคาปิดรายวัน [{date: "YYYY-MM-DD", close, volume}] เรียงเก่าไปใหม่ · period: 1M 3M 6M 1Y"""
    data = _get(f"/api/set/stock/{symbol.strip().upper()}/chart-quotation", period=period,
                accumulated="false") or {}
    return [{"date": q["localDatetime"][:10], "close": q["price"], "volume": q.get("volume")}
            for q in data.get("quotations", []) if q.get("price") is not None]


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

# ชื่อบัญชีในงบแบบย่อของ SET (ตัดช่องว่างแล้ว) แบบงบต่างกันตามประเภทธุรกิจ: ทั่วไป ธนาคาร ประกันภัย
# จับจากชื่อ เพราะรหัสบัญชีต่างกันตามแบบงบ · ค่าใน tuple = ชื่อที่ขึ้นต้นแบบนี้ (เรียงตามลำดับที่ลอง)
ACCOUNTS = {
    "revenue": ("รวมรายได้", "รายได้จากการประกันภัย"),
    "ebitda": ("EBITDA",),
    # ต้องเป็นกำไรส่วนของบริษัทใหญ่ ("กำไร(ขาดทุน)สุทธิจากเครื่องมือทางการเงิน..." ของธนาคารไม่ใช่กำไรสุทธิ)
    "net_profit": ("กำไร(ขาดทุน)สุทธิ:ผู้ถือหุ้นบริษัทใหญ่", "การแบ่งปันกำไร(ขาดทุน)สุทธิ:ผู้ถือหุ้นบริษัทใหญ่"),
    "eps": ("กำไรต่อหุ้น", "กำไร(ขาดทุน)ต่อหุ้น"),
    # ธนาคาร
    "nii": ("รายได้ดอกเบี้ยสุทธิ",),
    "fee_income": ("รายได้ค่าธรรมเนียมและบริการสุทธิ",),
    "credit_loss": ("(กลับรายการ)ผลขาดทุนด้านเครดิตที่คาดว่าจะเกิดขึ้น",),
    "opex": ("ค่าใช้จ่ายในการดำเนินงานอื่น",),
}
# รายได้จากการดำเนินงานของธนาคาร = ผลรวมบรรทัดเหล่านี้ (งบธนาคารไม่มีบรรทัด "รวมรายได้")
BANK_INCOME = ("รายได้ดอกเบี้ยสุทธิ", "รายได้ค่าธรรมเนียมและบริการสุทธิ", "รายได้จากเงินปันผล",
               "กำไร(ขาดทุน)จากเงินลงทุน", "กำไร(ขาดทุน)สุทธิจากเครื่องมือทางการเงิน")
# งบฐานะการเงินของธนาคาร
# สินเชื่อใช้ยอดสุทธิหลังหักค่าเผื่อ (ยอดก่อนหักธนาคารส่วนใหญ่ไม่กรอกในงบย่อ)
BALANCE = {"loans": ("เงินให้สินเชื่อลูกหนี้และดอกเบี้ยค้างรับ",), "deposits": ("เงินรับฝาก",), "total_assets": ("รวมสินทรัพย์",)}
BANK_FORM = "ธุรกิจธนาคาร"
MONTHS = {"Q1": 3, "Q2": 3, "Q3": 3, "Q4": 3, "6M": 6, "9M": 9, "Q9": 12}


def _amount(a):
    # หน่วยในงบคือพันบาท (divider 1000) แปลงเป็นล้านบาท ยกเว้น EPS ที่เป็นบาท
    return a["amount"] * a["divider"] / 1e6 if a["divider"] != 1 else a["amount"]


def _match(statement, accounts):
    out = {}
    lines = [(a["accountName"].replace(" ", "").lstrip("-"), a) for a in statement.get("accounts", [])
             if a["amount"] is not None]
    for key, prefixes in accounts.items():
        for prefix in prefixes:
            hit = next((a for name, a in lines if name.startswith(prefix)), None)
            if hit:
                out[key] = _amount(hit)
                break
    return out


def _accounts(statement):
    out = _match(statement, ACCOUNTS)
    if "revenue" not in out and "nii" in out:
        out["revenue"] = sum(_amount(a) for a in statement.get("accounts", []) if a["amount"] is not None
                             and a["accountName"].replace(" ", "").startswith(BANK_INCOME))
    return out


def _period(statement):
    q = statement["quarter"]
    return f"{'ทั้งปี' if q == 'Q9' else q}/{statement['year']}"


def _million(v):
    return round(v / 1000, 2) if v is not None else None  # financial-data เป็นพันบาท


def _statements(symbol, account_type):
    """งบรวมรายไตรมาส/สะสมของปีล่าสุดที่มี เรียงใหม่สุดก่อน (ปีนี้ + ปีก่อน)"""
    out = []
    for year in (date.today().year, date.today().year - 1):  # ต้นปีอาจยังไม่มีงบของปีนี้
        out += [s for s in _get(f"/api/set/factsheet/{symbol}/financialstatement", language="th",
                                financialStatementType="Q", accountType=account_type, fiscalYear=year) or []
                if s.get("fsType") == "C"]
    return out


def company_profile(symbol):
    """หมวดธุรกิจและแบบงบของหุ้น (ใช้เลือกตัวชี้วัดให้ตรงประเภทธุรกิจ)"""
    p = _get(f"/api/set/stock/{symbol.strip().upper()}/profile", lang="th") or {}
    return {"name": p.get("name"), "industry": p.get("industryName"), "sector": p.get("sectorName"),
            "account_form": p.get("accountForm")}


def major_shareholders(symbol):
    """ผู้ถือหุ้นใหญ่ 10 อันดับแรก [{name, pct}] ตามสมุดทะเบียนล่าสุด"""
    data = _get(f"/api/set/stock/{symbol.strip().upper()}/shareholder", lang="th") or {}
    return [{"name": " ".join(s["name"].split()), "pct": s.get("percentOfShare")}
            for s in data.get("majorShareholders") or [] if not s.get("isThaiNVDR")]


def financials(symbol):
    """งบรวมของรอบล่าสุดเทียบช่วงเดียวกันปีก่อน + งบย้อนหลังรายปี + ข้อมูลตลาด (ตัวเงินเป็นล้านบาท)
    ธนาคารมีตัวเลขเพิ่ม: รายได้ดอกเบี้ยสุทธิ ค่าธรรมเนียม ผลขาดทุนด้านเครดิต สินเชื่อ เงินฝาก"""
    symbol = symbol.strip().upper()
    statements = _statements(symbol, "I")
    if not statements:
        raise SourceSkipped(f"ไม่พบงบการเงินของ {symbol} บน SET")
    latest = statements[0]
    prev = next((s for s in statements[1:]
                 if s["quarter"] == latest["quarter"] and s["year"] == latest["year"] - 1), None)
    prof = company_profile(symbol)

    cur = {"period": _period(latest), "end_date": latest["endDate"][:10], "status": latest.get("status"),
           "months": MONTHS.get(latest["quarter"]), "filed_url": latest.get("downloadUrl"), **_accounts(latest)}
    if prof.get("account_form") == BANK_FORM:
        bal = next((s for s in _statements(symbol, "B")
                    if s["quarter"] == latest["quarter"] and s["year"] == latest["year"]), None)
        if bal:
            cur.update(_match(bal, BALANCE))

    history = [{
        "year": h["year"], "period": "ทั้งปี" if h["quarter"] == "Q9" else h["quarter"],
        "end_date": (h.get("endDate") or "")[:10],
        "revenue": _million(h.get("totalRevenue")), "net_profit": _million(h.get("netProfit")),
        "net_margin": h.get("netProfitMargin"), "roe": h.get("roe"), "de_ratio": h.get("deRatio"),
    } for h in _get(f"/api/set/stock/{symbol}/company-highlight/financial-data", lang="th") or []]

    market = _get(f"/api/set/stock/{symbol}/highlight-data", lang="th") or {}
    return {
        "symbol": symbol,
        "profile": prof,
        "latest": cur,
        "previous": ({"period": _period(prev), **_accounts(prev)} if prev else None),
        "history": history,
        "market": {"market_cap": round(market["marketCap"] / 1e6) if market.get("marketCap") else None,  # บาท
                   "pe": market.get("peRatio"), "dividend_yield": market.get("dividendYield"),
                   "as_of": (market.get("asOfDate") or "")[:10]},
    }
