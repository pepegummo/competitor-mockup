"""ติดตามอัตโนมัติ: เก็บตัวเลขของแต่ละรอบ (snapshot) เทียบกับรอบก่อนว่าอะไรเปลี่ยน แล้วแจ้งเตือน
กฎการแจ้งเตือนคิดด้วย pandas ไม่ใช้ LLM (ไม่เสียค่า LLM เพิ่ม และไม่แต่งเรื่อง)
level: "high" = ควรรู้ทันที (ส่งแจ้งเตือน), "info" = ดูในแอป"""
import os
from datetime import timedelta

import pandas as pd
import requests

WINDOW_DAYS = 30        # ตัวเลขใน snapshot คิดจากข่าว/รีวิวที่เผยแพร่ใน 30 วันล่าสุด
MIN_NEWS = 5            # ข่าวน้อยกว่านี้ % น้ำเสียงแกว่งง่าย ไม่เตือน
NEG_JUMP_PTS = 10       # ข่าวลบเปลี่ยนตั้งแต่ 10 จุด
STAR_JUMP = 0.3         # คะแนนรีวิวเปลี่ยนตั้งแต่ 0.3 ดาว
MAX_ITEMS = 5           # รายการต่อเรื่อง


def _num(x, digits=1):
    return None if x is None or pd.isna(x) else round(float(x), digits)


def snapshot(df, fin, moves=None):
    """ตัวเลขต่อบริษัท ณ รอบนี้ {บริษัท: {news_30d, negative_pct_30d, ..., fin_period, ..., price_moves}}
    moves = impact.big_moves(): วันที่ราคาหุ้นขยับผิดปกติหลังข่าว"""
    out = {}
    names = set(df["company"]) if not df.empty else set()
    names |= set(fin.index) if fin is not None and not fin.empty else set()
    since = pd.Timestamp.now(tz="UTC") - timedelta(days=WINDOW_DAYS)
    recent = df[df["published_dt"] >= since] if not df.empty else df
    for name in names:
        s = {}
        sub = recent[recent["company"] == name] if not recent.empty else recent
        news = sub[sub["source_type"] != "review"] if not sub.empty else sub
        s["news_30d"] = len(news)
        if len(news):
            s["negative_pct_30d"] = _num((news["sentiment"] == "negative").mean() * 100)
            s["positive_pct_30d"] = _num((news["sentiment"] == "positive").mean() * 100)
        reviews = sub[sub["source_type"] == "review"] if not sub.empty else sub
        if len(reviews) and reviews["rating"].notna().any():
            s["reviews_30d"] = len(reviews)
            s["stars_30d"] = _num(reviews["rating"].mean(), 2)
        if fin is not None and not fin.empty and name in fin.index:
            f = fin.loc[name]
            s["fin_period"] = f.get("period")
            for col in ("revenue_yoy_pct", "net_profit_yoy_pct", "net_profit_mb"):
                s[col] = _num(f.get(col))
        if moves is not None:
            s["price_moves"] = (moves or {}).get(name, [])
        out[name] = s
    return out


def _items(rows):
    return [{"title": r["title"], "url": r["url"]} for _, r in rows.head(MAX_ITEMS).iterrows()]


def changes(companies, df, snap, previous, events=None):
    """เทียบกับรอบก่อนของแต่ละบริษัท previous = {บริษัท: (เวลาเริ่มรอบก่อน, snapshot)}
    บริษัทที่ยังไม่มีรอบก่อนจะไม่ถูกเตือน (ข้อมูลทั้งหมดใหม่หมด) · events = impact.events() ใช้บอกข่าวที่ทำให้หุ้นขยับ"""
    out = []

    def add(company, level, kind, text, items=None):
        out.append({"company": company, "level": level, "kind": kind, "text": text, "items": items or []})

    for name in companies:
        if name not in previous:
            continue
        since, old = previous[name]
        cur = snap.get(name, {})
        new = df[(df["company"] == name) & (df["fetched_at"] > since)] if not df.empty else df
        if not new.empty:
            news = new[new["source_type"] != "review"].sort_values("published_dt", ascending=False)
            sets = news[news["source_type"] == "set"]
            if not sets.empty:
                add(name, "high", "set", f"แจ้งตลาดใหม่ {len(sets)} เรื่อง", _items(sets))
            neg = news[(news["sentiment"] == "negative") & (news["source_type"] != "set")]
            if not neg.empty:
                add(name, "high", "negative", f"ข่าวลบใหม่ {len(neg)} ข่าว", _items(neg))
            promo = news[news["category"].isin(["promotion", "product_price"])
                         & (news["sentiment"] != "negative") & (news["source_type"] != "set")]
            if not promo.empty:
                add(name, "info", "promotion", f"ข่าวสินค้า/โปรโมชันใหม่ {len(promo)} ข่าว", _items(promo))
            reviews = new[new["source_type"] == "review"]
            add(name, "info", "volume", f"ข้อมูลใหม่ตั้งแต่รอบก่อน: ข่าว {len(news)} · รีวิว {len(reviews)}")

        if "price_moves" in old and cur.get("price_moves"):  # รอบก่อนยังไม่มีข้อมูลนี้ = ไม่เตือนย้อนหลัง
            for day in sorted(set(cur["price_moves"]) - set(old["price_moves"])):
                ev = events[(events["company"] == name) & (events["date"] == day)].iloc[0]
                move = ev["r3_pct"] if pd.notna(ev["r3_pct"]) else ev["r1_pct"]
                add(name, "high", "price_move",
                    f"หุ้น {ev['symbol']} ขยับ {move:+.1f}% หลังข่าววันที่ {day} ({abs(ev['z']):.1f} เท่าของปกติ)",
                    [{"title": t, "url": u} for t, u in zip(ev["titles"], ev["urls"])])

        if cur.get("fin_period") and cur.get("fin_period") != old.get("fin_period"):
            growth = cur.get("net_profit_yoy_pct")
            add(name, "high", "financials", f"งบใหม่ {cur['fin_period']}"
                + (f": กำไรสุทธิ {growth:+.1f}% YoY" if growth is not None else ""))

        if min(cur.get("news_30d", 0), old.get("news_30d", 0)) >= MIN_NEWS:
            a, b = old.get("negative_pct_30d"), cur.get("negative_pct_30d")
            if a is not None and b is not None and abs(b - a) >= NEG_JUMP_PTS:
                add(name, "high" if b > a else "info", "sentiment",
                    f"ข่าวลบ 30 วันล่าสุด {'เพิ่ม' if b > a else 'ลด'}จาก {a:.0f}% เป็น {b:.0f}%")

        if min(cur.get("reviews_30d", 0), old.get("reviews_30d", 0)) >= MIN_NEWS:
            a, b = old.get("stars_30d"), cur.get("stars_30d")
            if a is not None and b is not None and abs(b - a) >= STAR_JUMP:
                add(name, "high" if b < a else "info", "reviews",
                    f"คะแนนรีวิว 30 วันล่าสุด {'ลด' if b < a else 'เพิ่ม'}จาก {a:.1f} เป็น {b:.1f} ดาว")
    order = {"high": 0, "info": 1}
    return sorted(out, key=lambda c: (order[c["level"]], companies.index(c["company"])))


# ---------- แจ้งเตือน ----------

def webhook_url():
    return os.environ.get("ALERT_WEBHOOK_URL", "").strip()


def alert_text(title, changes_list, only_high=True):
    rows = [c for c in changes_list if c["level"] == "high" or not only_high]
    if not rows:
        return None
    lines = [f"📊 {title}"]
    for c in rows:
        lines.append(f"• {c['company']}: {c['text']}")
        lines += [f"   - {it['title']} {it['url'] or ''}".rstrip() for it in c["items"][:3]]
    return "\n".join(lines)


def send_alert(text):
    """ส่งไป webhook ที่ตั้งไว้ใน .env (Discord / Slack / Microsoft Teams / Google Chat)
    คืน (สำเร็จไหม, ข้อความ)"""
    url = webhook_url()
    if not url:
        return False, "ยังไม่ได้ตั้ง ALERT_WEBHOOK_URL ใน .env"
    payload = {"content": text[:1900]} if "discord" in url else {"text": text}
    try:
        r = requests.post(url, json=payload, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        return False, f"ส่งไม่สำเร็จ ({type(e).__name__})"
    return True, "ส่งแล้ว"
