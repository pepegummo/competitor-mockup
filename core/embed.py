"""ค้นด้วยความหมาย (embedding) ให้แท็บถามข้อมูล: คำถาม "เน็ตบ้าน" เจอข่าว "บรอดแบนด์" แม้คำไม่ตรงกัน
ข้อความ (หัวข้อ + สรุป) ถูกแปลงเป็นเวกเตอร์แล้วเก็บในตาราง embeddings คำนวณครั้งเดียวต่อข้อความ
EMBED_BACKEND=local (ค่าเริ่ม): รันโมเดลในเครื่องด้วย sentence-transformers (ครั้งแรกโหลดโมเดล ~470MB)
EMBED_BACKEND=api: เรียก /v1/embeddings ของ endpoint เดียวกับ LLM (ใช้เมื่อมีโมเดล embedding ให้ใช้)
ใช้ไม่ได้ (ไม่ได้ลงไลบรารี เน็ตล่ม ฯลฯ) → similarity() คืน None แท็บถามข้อมูลใช้คำค้นอย่างเดียวเหมือนเดิม"""
import hashlib
import logging
import os
import threading

import numpy as np
import pandas as pd
import requests

from core import db, llm

BACKEND = os.environ.get("EMBED_BACKEND", "local").strip().lower()
MODEL = os.environ.get("EMBED_MODEL", "").strip() or (
    "intfloat/multilingual-e5-small" if BACKEND == "local" else llm.MODEL)
BATCH = 64
MIN_TITLE = 10  # รีวิวสั้น ๆ ("." "ห่วยแตก") ใกล้กับทุกคำถาม ไม่นับในการค้นด้วยความหมาย

log = logging.getLogger(__name__)
_model = None
_lock = threading.Lock()


def _text(title, summary):
    return f"{title or ''} {summary or ''}".strip()[:500]


def _hash(kind, text):
    return hashlib.sha256(f"{MODEL}\n{kind}\n{text}".encode("utf-8")).hexdigest()


def _local(texts, kind):
    global _model
    with _lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer  # import ช้า: โหลดเมื่อใช้ครั้งแรกเท่านั้น
            _model = SentenceTransformer(MODEL, device="cpu")
    if "e5" in MODEL:  # โมเดลตระกูล e5 ต้องบอกว่าเป็นคำถามหรือเนื้อหา
        texts = [f"{kind}: {t}" for t in texts]
    return _model.encode(texts, batch_size=BATCH, normalize_embeddings=True, convert_to_numpy=True)


def _api(texts, kind):
    r = requests.post(llm.URL.replace("/chat/completions", "/embeddings"),
                      json={"model": MODEL, "input": texts, "encoding_format": "float"},
                      headers={"Authorization": f"Bearer {llm._api_key()}"}, timeout=120)
    r.raise_for_status()
    v = np.array([d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])], dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def vectors(texts, kind="passage"):
    """เวกเตอร์ (normalize แล้ว) ของแต่ละข้อความ เรียงตาม texts · ใช้ cache ในตาราง embeddings"""
    keys = [_hash(kind, t) for t in texts]
    have = db.get_embeddings(set(keys))
    missing = list(dict.fromkeys(k for k in keys if k not in have))
    if missing:
        text_of = dict(zip(keys, texts))
        fresh = {}
        for i in range(0, len(missing), BATCH):
            part = missing[i:i + BATCH]
            vecs = (_api if BACKEND == "api" else _local)([text_of[k] for k in part], kind)
            fresh.update({k: np.asarray(v, dtype=np.float32).tobytes() for k, v in zip(part, vecs)})
        db.save_embeddings(fresh, MODEL)
        have.update(fresh)
    return np.stack([np.frombuffer(have[k], dtype=np.float32) for k in keys])


def warm(df):
    """คำนวณเวกเตอร์ของข่าวใหม่ไว้ล่วงหน้า (ตอนวิเคราะห์เบื้องหลัง) คำถามแรกในแท็บถามข้อมูลจะได้ไม่ช้า · คืนจำนวนรายการ"""
    if df.empty:
        return 0
    try:
        vectors([_text(t, s) for t, s in zip(df["title"], df["summary"])], "passage")
    except Exception as e:  # noqa: BLE001
        log.warning("คำนวณเวกเตอร์ล่วงหน้าไม่ได้: %s", e)
        return 0
    return len(df)


def similarity(question, df):
    """ความใกล้ของคำถามกับแต่ละรายการ (cosine, index เดียวกับ df) หรือ None ถ้าใช้ embedding ไม่ได้"""
    if df.empty:
        return None
    try:
        docs = vectors([_text(t, s) for t, s in zip(df["title"], df["summary"])], "passage")
        q = vectors([question], "query")[0]
    except Exception as e:  # noqa: BLE001 ไม่มีโมเดล/เน็ต: ถามข้อมูลยังใช้คำค้นได้
        log.warning("ค้นด้วยความหมายไม่ได้ ใช้คำค้นอย่างเดียว: %s", e)
        return None
    sims = pd.Series(docs @ q, index=df.index)
    sims[df["title"].fillna("").str.strip().str.len() < MIN_TITLE] = 0.0
    return sims


if __name__ == "__main__":
    db.init_db()
    texts = ["True ออกโปรบรอดแบนด์ไฟเบอร์ 1Gbps ราคาใหม่", "AIS กำไรไตรมาส 3 เพิ่มขึ้น", "ฝนตกหนักกรุงเทพ"]
    sims = similarity("ใครออกแพ็กเกจเน็ตบ้านใหม่", pd.DataFrame({"title": texts, "summary": [""] * 3}))
    print(BACKEND, MODEL)
    print(sims.round(3).tolist() if sims is not None else "ใช้ไม่ได้")
