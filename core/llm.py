import hashlib, os, re, json, time, requests
from dotenv import load_dotenv

from core import db

load_dotenv()
URL = "https://llm.nattee.net/v1/chat/completions"
MODEL = "qwen3.5"

# นับจำนวนครั้งที่เรียก LLM จริง (ใช้ตรวจว่ารันซ้ำแล้วไม่เรียกซ้ำ) · replay_count = ตอบจาก log โดยไม่เรียกจริง
call_count = 0
replay_count = 0


def _api_key():
    key = os.environ.get("LLM_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ยังไม่ได้ใส่ LLM_API_KEY ในไฟล์ .env")
    return key


def replay_on():
    """LLM_REPLAY=1: คำถามที่เคยถามแล้ว (prompt เดิมทุกตัวอักษร) ใช้คำตอบเดิมจาก llm_log ไม่เรียกเครื่อง LLM
    ใช้ตอนเดโม (ไม่ต้องพึ่งเน็ต/เครื่อง LLM) และทำให้ผลซ้ำได้"""
    return os.environ.get("LLM_REPLAY", "").strip().lower() in ("1", "true", "yes")


def _hash(prompt, system):
    return hashlib.sha256(f"{MODEL}\n{system or ''}\n{prompt}".encode("utf-8")).hexdigest()


def chat(prompt, system=None, retries=3):
    """ทุก call ถูกบันทึกใน llm_log (prompt, คำตอบ, เวลา) · ถ้าเรียกไม่สำเร็จแต่เคยถาม prompt นี้แล้ว ใช้คำตอบเดิม"""
    global call_count, replay_count
    key = _hash(prompt, system)
    if replay_on():
        cached = db.llm_cached(key)
        if cached is not None:
            replay_count += 1
            return cached
    messages = [{"role": "system", "content": system}] if system else []
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": MODEL,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": messages,
    }
    headers = {"Authorization": f"Bearer {_api_key()}"}
    for attempt in range(retries):
        try:
            call_count += 1
            start = time.monotonic()
            r = requests.post(URL, json=payload, headers=headers, timeout=120)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            db.log_llm(key, MODEL, prompt if not system else f"[system]\n{system}\n\n{prompt}", text,
                       int((time.monotonic() - start) * 1000))
            return text
        except requests.RequestException:
            if attempt == retries - 1:
                cached = db.llm_cached(key)  # เครื่อง LLM ล่ม: ถ้าเคยถามคำถามนี้แล้วใช้คำตอบเดิม
                if cached is not None:
                    replay_count += 1
                    return cached
                raise
            time.sleep(2 ** attempt)


def chat_json(prompt, system=None):
    """ใช้เมื่อสั่งให้ LLM ตอบเป็น JSON — ตัด ``` ออกก่อน parse"""
    text = chat(prompt, system).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)


if __name__ == "__main__":
    print(chat("Say hello in Thai"))
    print(chat_json('Return only JSON: {"ok": true}'))
