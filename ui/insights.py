"""ประโยคสั้น ๆ บอกว่ากราฟแต่ละอันแสดงอะไร คิดจากตารางด้วย pandas (ไม่ใช้ LLM จึงไม่แต่งตัวเลข)"""
import pandas as pd

from ui.labels import CATEGORY_TH, GAP_ITEM_TH

# ทิศทางที่ "ดี" ของแต่ละรายการใน gap (หมวดข่าวไม่มีดี/แย่ แค่เน้นต่างกัน)
GOOD_IF_HIGHER = {"positive": True, "neutral": None, "negative": False, "avg_stars": True,
                  "negative_pct": False, "revenue_yoy_pct": True, "net_margin_pct": True, "roe_pct": True}


def _unit(item):
    return " ดาว" if item == "avg_stars" else " จุด"


def sentiment(table_b):
    if table_b.empty or len(table_b) < 2:
        return []
    pos, neg = table_b["positive"], table_b["negative"]
    out = [f"ข่าวบวกมากที่สุด: **{pos.idxmax()}** ({pos.max():.0f}%)"]
    if neg.max() > 0:
        out.append(f"ข่าวลบมากที่สุด: **{neg.idxmax()}** ({neg.max():.0f}%)")
    return out


def categories(news):
    if news.empty:
        return []
    share = pd.crosstab(news["company"], news["category"], normalize="index") * 100
    return [f"**{c}** เน้น{CATEGORY_TH.get(share.loc[c].idxmax(), share.loc[c].idxmax())} "
            f"({share.loc[c].max():.0f}% ของข่าว)" for c in share.index]


def gap(gap_df, self_name):
    """จุดที่เราดีกว่า/แย่กว่าคู่แข่งมากที่สุดอย่างละ 2 อัน + หมวดที่เราเน้นต่างที่สุด"""
    if gap_df.empty:
        return [], []
    rows = gap_df[gap_df["item"].map(lambda i: GOOD_IF_HIGHER.get(i) is not None)].copy()
    rows["score"] = rows.apply(lambda r: r["gap_pts"] if GOOD_IF_HIGHER[r["item"]] else -r["gap_pts"], axis=1)

    def line(r):
        unit = _unit(r["item"])
        return (f"{GAP_ITEM_TH.get(r['item'], r['item'])}: เรา {r['us_pct']:g} เทียบคู่แข่งเฉลี่ย "
                f"{r['competitor_avg_pct']:g} (ต่าง {r['gap_pts']:+g}{unit})")
    ahead = [line(r) for _, r in rows[rows["score"] > 0].nlargest(2, "score").iterrows()]
    behind = [line(r) for _, r in rows[rows["score"] < 0].nsmallest(2, "score").iterrows()]
    cat = gap_df[gap_df["type"] == "category"]
    if not cat.empty:
        top = cat.loc[cat["gap_pts"].abs().idxmax()]
        word = "มากกว่า" if top["gap_pts"] > 0 else "น้อยกว่า"
        ahead_or = f"{self_name} เน้นข่าว{CATEGORY_TH.get(top['item'], top['item'])}{word}คู่แข่ง {abs(top['gap_pts']):.0f} จุด"
        (ahead if top["gap_pts"] > 0 else behind).append(ahead_or + " (ไม่ได้แปลว่าดีหรือแย่)")
    return ahead, behind


def reviews(table_r):
    if table_r.empty:
        return []
    out = [f"คะแนนรีวิวสูงสุด: **{table_r['avg_stars'].idxmax()}** ({table_r['avg_stars'].max():.1f} ดาว)"]
    if len(table_r) > 1:
        out.append(f"รีวิวลบมากที่สุด: **{table_r['negative_pct'].idxmax()}** ({table_r['negative_pct'].max():.0f}% ของรีวิว)")
    return out


def finance(fin):
    if fin.empty:
        return []
    out = []
    for col, label in (("revenue_yoy_pct", "รายได้โตมากที่สุด"), ("net_margin_pct", "อัตรากำไรสุทธิสูงสุด")):
        s = fin[col].dropna()
        if not s.empty:
            out.append(f"{label}: **{s.idxmax()}** ({s.max():+.1f}%)" if "yoy" in col
                       else f"{label}: **{s.idxmax()}** ({s.max():.1f}%)")
    return out


def show(st, lines):
    if lines:
        st.markdown("\n".join(f"- {line}" for line in lines))
