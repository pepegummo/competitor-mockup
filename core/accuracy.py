"""วัดความแม่นของระบบจากข่าวที่ผู้ใช้ตรวจแล้ว (ตาราง labels) ตัวเลขคิดด้วย pandas
- ข่าวที่ระบบเก็บไว้ เกี่ยวกับบริษัทจริงกี่ % (precision ฝั่งเก็บ)
- ข่าวที่ระบบตัดออก ไม่เกี่ยวจริงกี่ % (precision ฝั่งตัด)
- จับข่าวไม่เกี่ยวได้กี่ % ของข่าวไม่เกี่ยวทั้งหมด (recall ประมาณจากสัดส่วนในฐานข้อมูล เพราะคิวตรวจดึงข่าวที่ตัดออกมาเกินสัดส่วนจริง)
- หมวดและน้ำเสียงถูกกี่ % (เฉพาะข่าวที่เกี่ยวจริง)"""
from core import db

MIN_LABELS = 5  # น้อยกว่านี้ยังไม่แสดงตัวเลข


def _pct(x):
    return round(float(x) * 100, 1)


def metrics():
    """{"labeled", "kept_ok", "kept_n", "dropped_ok", "dropped_n", "recall", "category_ok", "category_n",
    "sentiment_ok", "sentiment_n"} ค่าเป็น % หรือ None ถ้าตัวอย่างยังน้อย"""
    df = db.labels_df()
    out = {"labeled": len(df)}
    if df.empty:
        return out
    system_kept = df["category"] != "irrelevant"
    human_rel = df["human_relevant"] == 1
    kept, dropped = df[system_kept], df[~system_kept]
    out.update(kept_n=len(kept), dropped_n=len(dropped))
    out["kept_ok"] = _pct(human_rel[system_kept].mean()) if len(kept) >= MIN_LABELS else None
    out["dropped_ok"] = _pct((~human_rel[~system_kept]).mean()) if len(dropped) >= MIN_LABELS else None
    if out["kept_ok"] is not None and out["dropped_ok"] is not None:
        pop = db.label_population()
        caught = out["dropped_ok"] / 100 * pop["dropped"]
        missed = (1 - out["kept_ok"] / 100) * pop["kept"]
        out["recall"] = _pct(caught / (caught + missed)) if caught + missed else None
    rel = df[human_rel & system_kept]
    for field in ("category", "sentiment"):
        checked = rel[rel[f"human_{field}"].notna()]
        out[f"{field}_n"] = len(checked)
        out[f"{field}_ok"] = (_pct((checked[field] == checked[f"human_{field}"]).mean())
                              if len(checked) >= MIN_LABELS else None)
    return out


def mistakes(limit=20):
    """ข่าวที่ระบบตัดสินต่างจากผู้ใช้ ล่าสุดก่อน"""
    df = db.labels_df()
    if df.empty:
        return df
    wrong_rel = (df["category"] == "irrelevant") != (df["human_relevant"] == 0)
    wrong_cat = df["human_category"].notna() & (df["human_category"] != df["category"]) & ~wrong_rel
    wrong_sent = df["human_sentiment"].notna() & (df["human_sentiment"] != df["sentiment"]) & ~wrong_rel
    df = df.assign(ผิดเรื่อง=wrong_rel.map({True: "เกี่ยว/ไม่เกี่ยว", False: ""})
                   + wrong_cat.map({True: " หมวด", False: ""}) + wrong_sent.map({True: " น้ำเสียง", False: ""}))
    return df[df["ผิดเรื่อง"].str.strip() != ""].iloc[::-1].head(limit)
