"""เทียบกับทุกบริษัทจดทะเบียนในหมวดธุรกิจเดียวกันของ SET: อันดับและเปอร์เซ็นไทล์
ตัวเลขมาจาก SET (set_api.highlight) คิดด้วย pandas ไม่ผ่าน LLM · เก็บใน market_cache 1 วัน
refresh() ดึงจาก SET (ใช้ตอนวิเคราะห์) ส่วน frames()/table() อ่านจาก DB อย่างเดียว (ใช้ตอนแสดงผล)"""
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from core import db
from core.sources import SourceSkipped, set_api

MAX_AGE_HOURS = 24
MIN_PEERS = 3
# True = ยิ่งสูงยิ่งดี · False = ยิ่งต่ำยิ่งดี · None = ไม่ตัดสินดี/แย่ (P/E ต่ำ = ราคาถูกเมื่อเทียบกำไร)
METRICS = {"revenue_yoy_pct": True, "net_profit_yoy_pct": True, "net_margin_pct": True, "roe_pct": True,
           "de_ratio": False, "market_cap_mb": True, "pe": None, "dividend_yield_pct": True}
METRIC_TH = {"revenue_yoy_pct": "รายได้โต (%)", "net_profit_yoy_pct": "กำไรโต (%)",
             "net_margin_pct": "อัตรากำไรสุทธิ (%)", "roe_pct": "ROE (%)", "de_ratio": "D/E (เท่า)",
             "market_cap_mb": "มูลค่าตลาด (ลบ.)", "pe": "P/E (เท่า)", "dividend_yield_pct": "ปันผล (%)"}


def _print(text):
    print(text, flush=True)


def symbols_of(names):
    """{ชื่อบริษัท: ชื่อหุ้น} ของบริษัทที่อยู่ในตลาด (จากชื่อหุ้นที่บันทึกไว้)"""
    return {r["name"]: r["set_symbol"] for r in db.get_companies(names) if r.get("set_symbol")}


def refresh(symbols, log=_print):
    """ดึงตัวเลขของทุกหุ้นในหมวดเดียวกับ symbols ที่ยังไม่มีหรือเก่ากว่า 1 วัน คืนจำนวนหุ้นที่ดึงใหม่"""
    symbols = sorted(set(symbols))
    groups = db.get_cache([f"grp:{s}" for s in symbols], MAX_AGE_HOURS)
    for s in symbols:
        if f"grp:{s}" in groups:
            continue
        try:
            code, members = set_api.peers(s)
            sector_name = set_api.company_profile(s).get("sector") or code
        except SourceSkipped as e:
            log(f"{s} · {e}")
            continue
        groups[f"grp:{s}"] = {"group": code, "name": sector_name, "peers": members}
        db.set_cache(f"grp:{s}", groups[f"grp:{s}"])
    todo = sorted({p for g in groups.values() for p in g["peers"]})
    have = db.get_cache([f"hl:{p}" for p in todo], MAX_AGE_HOURS)
    missing = [p for p in todo if f"hl:{p}" not in have]
    if not missing:
        return 0

    def one(symbol):
        try:
            return symbol, set_api.highlight(symbol)
        except SourceSkipped:
            return symbol, None

    with ThreadPoolExecutor(4) as pool:  # ~0.7 วินาทีต่อหุ้น หมวดหนึ่งมี 30–60 หุ้น
        for symbol, data in pool.map(one, missing):
            if data:
                db.set_cache(f"hl:{symbol}", data)
    return len(missing)


def frames(symbols):
    """{ชื่อหุ้น: {"group", "name", "df"}} ทุกหุ้นในหมวดของแต่ละ symbol (index = ชื่อหุ้น) จาก DB เท่านั้น"""
    groups = db.get_cache([f"grp:{s}" for s in symbols])
    out = {}
    for s in symbols:
        g = groups.get(f"grp:{s}")
        if not g:
            continue
        rows = list(db.get_cache([f"hl:{p}" for p in g["peers"]]).values())
        if len(rows) < MIN_PEERS:
            continue
        out[s] = {"group": g["group"], "name": g["name"], "df": pd.DataFrame(rows).set_index("symbol")}
    return out


def percentiles(df):
    """เปอร์เซ็นไทล์ 0–100 ของทุกหุ้นในทุกตัวชี้วัด ยิ่งมากยิ่งดี (D/E และ P/E กลับด้าน: ต่ำ = ขวา)"""
    out = pd.DataFrame(index=df.index)
    for m, higher in METRICS.items():
        if m in df:
            out[m] = (df[m].rank(pct=True, ascending=higher is True) * 100).round()
    return out


def table(companies):
    """ตาราง long: company, symbol, sector, metric, value, rank, n, percentile, median
    rank 1 = ดีที่สุดในหมวด (D/E ต่ำสุด, P/E ต่ำสุด) · companies = {ชื่อบริษัท: ชื่อหุ้น}"""
    fr = frames(list(companies.values()))
    rows = []
    for name, symbol in companies.items():
        if symbol not in fr:
            continue
        df = fr[symbol]["df"]
        for m, higher in METRICS.items():
            col = df[m].dropna() if m in df else pd.Series(dtype=float)
            if symbol not in col.index or len(col) < MIN_PEERS:
                continue
            rank = col.rank(ascending=higher is not True, method="min")
            rows.append({"company": name, "symbol": symbol, "sector": fr[symbol]["name"], "metric": m,
                         "value": round(float(col[symbol]), 2), "rank": int(rank[symbol]), "n": len(col),
                         "percentile": int(round(float(col.rank(pct=True, ascending=higher is True)[symbol]) * 100)),
                         "median": round(float(col.median()), 2)})
    return pd.DataFrame(rows)


def suggest(symbol, exclude=(), n=5):
    """บริษัทใหญ่สุดในหมวดเดียวกัน (ตามมูลค่าตลาด) ที่ยังไม่ได้เลือก · ดึงจาก SET ถ้ายังไม่มีใน DB"""
    refresh([symbol])
    fr = frames([symbol])
    if symbol not in fr:
        return []
    caps = fr[symbol]["df"]["market_cap_mb"].dropna().sort_values(ascending=False)
    skip = {e.upper() for e in exclude} | {symbol}
    return [s for s in caps.index if s not in skip][:n]


JUDGED = [m for m, higher in METRICS.items() if higher is not None and m != "market_cap_mb"]


def _short(metric):
    return METRIC_TH[metric].split(" (")[0]


def highlights(tb):
    """1 บรรทัดต่อบริษัท: ตัวชี้วัดที่อันดับดีสุดในหมวด และจุดอ่อน (ถ้าต่ำกว่าครึ่งหมวด)"""
    lines = []
    if tb.empty:
        return lines
    for (name, sector), g in tb.groupby(["company", "sector"], sort=False):
        g = g[g["metric"].isin(JUDGED)].sort_values("percentile", ascending=False)
        if g.empty:
            continue
        best, worst = g.iloc[0], g.iloc[-1]
        line = (f"**{name}** ในหมวด{sector}: {_short(best['metric'])} อันดับ {best['rank']} จาก {best['n']} บริษัท "
                f"({best['value']:,.2f} เทียบมัธยฐาน {best['median']:,.2f})")
        if worst["percentile"] < 50:
            line += (f" · จุดอ่อนคือ{_short(worst['metric'])} อันดับ {worst['rank']} จาก {worst['n']} "
                     f"({worst['value']:,.2f} เทียบมัธยฐาน {worst['median']:,.2f})")
        lines.append(line)
    return lines
