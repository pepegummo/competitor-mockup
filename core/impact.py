"""ราคาหุ้นหลังข่าว: วันที่มีข่าว/ประกาศ หุ้นขยับเท่าไรใน 1 และ 3 วันทำการ หักผลของตลาดรวมแล้ว (abnormal return
= ผลตอบแทนหุ้น − ผลตอบแทนดัชนี SET หรือ mai ช่วงเดียวกัน) เทียบกับความผันผวนปกติของส่วนต่างนั้น
ใช้แยกข่าวที่ตลาดสนใจจริงออกจากวันที่ทั้งตลาดขึ้นลง · ราคาจาก SET คิดด้วย pandas ไม่ผ่าน LLM
ข้อจำกัด: ยังไม่หักวันขึ้นเครื่องหมาย XD และวันเดียวอาจมีหลายข่าว (นับเป็น 1 เหตุการณ์ แสดงทุกหัวข้อ)"""
import math

import pandas as pd

from core import db
from core.sources import SourceSkipped, set_api

PERIOD = "6M"
MAX_AGE_HOURS = 6
Z_LIMIT = 2.0           # ขยับเกิน 2 เท่าของความผันผวนปกติ = ผิดปกติ
MIN_DAYS = 20           # ราคาน้อยกว่านี้คิดความผันผวนไม่ได้
SOURCES = ("news", "rss", "set")
CLOSE = (16, 30)        # ข่าวหลังตลาดปิด (16:30) นับเป็นข่าวของวันทำการถัดไป


def _print(text):
    print(text, flush=True)


def refresh(symbols, log=_print):
    """ดึงราคาปิดรายวัน 6 เดือนของหุ้นและดัชนีตลาดที่ใช้เทียบ (เก็บเป็น px:^SET, px:^mai)
    เฉพาะที่ยังไม่มีหรือเก่ากว่า 6 ชั่วโมง คืนจำนวนที่ดึงใหม่"""
    symbols = sorted(set(symbols))
    keys = symbols + sorted({"^" + _market(s) for s in symbols})
    have = db.get_cache([f"px:{k}" for k in keys], MAX_AGE_HOURS)
    n = 0
    for k in keys:
        if f"px:{k}" in have:
            continue
        try:
            rows = set_api.index_history(k[1:], PERIOD) if k.startswith("^") else set_api.price_history(k, PERIOD)
            db.set_cache(f"px:{k}", rows)
            n += 1
        except SourceSkipped as e:
            log(f"{k} · ราคา: {e}")
    return n


def _market(symbol):
    try:
        return set_api.market_of(symbol)
    except SourceSkipped:
        return "SET"


def prices(symbols):
    """{ชื่อหุ้น: Series ราคาปิด index = วันที่} จาก DB เท่านั้น"""
    out = {}
    for key, rows in db.get_cache([f"px:{s}" for s in symbols]).items():
        if rows:
            s = pd.DataFrame(rows).assign(date=lambda d: pd.to_datetime(d["date"])).set_index("date")["close"]
            out[key[3:]] = s.sort_index()
    return out


def _event_day(ts):
    local = ts.tz_convert("Asia/Bangkok").tz_localize(None)
    day = local.normalize()
    return day + pd.Timedelta(days=1) if (local.hour, local.minute) >= CLOSE else day


def _pick(group, n=3):
    """หัวข้อที่น่าจะเป็นต้นเหตุ: ประกาศ SET ก่อน แล้วข่าวลบ แล้วข่าวอื่น"""
    order = group.assign(_o=group["source_type"].ne("set").astype(int) * 2
                         + group["sentiment"].ne("negative").astype(int))
    return order.sort_values("_o").head(n)


def events(df, companies):
    """ต่อบริษัทต่อวันที่มีข่าว: ผลตอบแทน 1 และ 3 วันทำการ และ z (เท่าของความผันผวนปกติ)
    companies = {ชื่อบริษัท: ชื่อหุ้น} · คืน DataFrame เรียงจากขยับผิดปกติมากสุด"""
    if df.empty or not companies:
        return pd.DataFrame()
    px = prices(set(companies.values()) | {"^SET", "^mai"})
    news = df[df["source_type"].isin(SOURCES)].dropna(subset=["published_dt"])
    rows = []
    for name, symbol in companies.items():
        s = px.get(symbol)
        if s is None or len(s) < MIN_DAYS:
            continue
        dates = s.index
        m = px.get("^" + _market(symbol))
        m = m.reindex(dates).ffill() if m is not None else None  # ดัชนีวันเดียวกับราคาหุ้น
        adjusted = m is not None and m.notna().sum() >= MIN_DAYS
        daily = s.pct_change() - (m.pct_change() if adjusted else 0)
        sd = daily.std()
        if not sd or math.isnan(sd):
            continue
        sub = news[news["company"] == name]
        if sub.empty:
            continue
        sub = sub.assign(day=sub["published_dt"].map(_event_day))
        for day, g in sub.groupby("day"):
            i = dates.searchsorted(day)  # วันทำการแรกตั้งแต่วันข่าว
            if i == 0 or i >= len(dates):
                continue  # ข่าวก่อนช่วงราคาที่มี หรือยังไม่มีราคาหลังข่าว
            base = s.iloc[i - 1]
            r1 = s.iloc[i] / base - 1
            r3 = s.iloc[i + 2] / base - 1 if i + 2 < len(dates) else None
            m1 = m.iloc[i] / m.iloc[i - 1] - 1 if adjusted else 0.0
            m3 = (m.iloc[i + 2] / m.iloc[i - 1] - 1 if adjusted else 0.0) if r3 is not None else None
            ar1 = r1 - m1
            ar3 = r3 - m3 if r3 is not None else None
            z1 = ar1 / sd
            z3 = ar3 / (sd * math.sqrt(3)) if ar3 is not None else None
            z = z3 if z3 is not None and abs(z3) > abs(z1) else z1
            top = _pick(g)
            rows.append({
                "company": name, "symbol": symbol, "date": dates[i].date().isoformat(),
                "close": float(s.iloc[i]), "news": len(g),
                "r1_pct": round(r1 * 100, 2), "r3_pct": round(r3 * 100, 2) if r3 is not None else None,
                "ar1_pct": round(ar1 * 100, 2), "ar3_pct": round(ar3 * 100, 2) if ar3 is not None else None,
                "market_r3_pct": round(m3 * 100, 2) if m3 is not None and adjusted else None,
                "adjusted": adjusted,
                "z": round(float(z), 1), "big": abs(z) >= Z_LIMIT,
                "sentiment": g["sentiment"].mode().iat[0] if g["sentiment"].notna().any() else "neutral",
                "titles": list(top["title"]), "urls": list(top["url"]),
            })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.reindex(out["z"].abs().sort_values(ascending=False).index).reset_index(drop=True)


def big_moves(ev, days=30):
    """{บริษัท: [วันที่ที่ขยับผิดปกติ ใน 30 วันล่าสุด]} ใช้ใน snapshot ของการติดตามอัตโนมัติ"""
    if ev is None or ev.empty:
        return {}
    since = (pd.Timestamp.now() - pd.Timedelta(days=days)).date().isoformat()
    recent = ev[ev["big"] & (ev["date"] >= since)]
    return {name: sorted(g["date"]) for name, g in recent.groupby("company")}


def describe(r):
    """ข้อความสั้นของ 1 เหตุการณ์ เช่น "−7.6% ใน 3 วัน (ตลาด −0.8% · หักตลาดแล้ว −6.7%, 4.4 เท่าของปกติ)" """
    three = pd.notna(r["r3_pct"])
    move = r["r3_pct"] if three else r["r1_pct"]
    text = f"{move:+.1f}% ใน {'3 วัน' if three else '1 วัน'}"
    if r.get("adjusted"):
        market = r["market_r3_pct"] if three else r["r1_pct"] - r["ar1_pct"]
        abnormal = r["ar3_pct"] if three else r["ar1_pct"]
        return text + f" (ตลาด {market:+.1f}% · หักตลาดแล้ว {abnormal:+.1f}%, {abs(r['z']):.1f} เท่าของปกติ)"
    return text + f" ({abs(r['z']):.1f} เท่าของปกติ)"
