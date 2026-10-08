import os, re, json, time, requests
from dotenv import load_dotenv

load_dotenv()
URL = "https://llm.nattee.net/v1/chat/completions"

# นับจำนวนครั้งที่เรียก LLM จริง (ใช้ตรวจว่ารันซ้ำแล้วไม่เรียกซ้ำ)
call_count = 0


def _api_key():
    key = os.environ.get("LLM_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ยังไม่ได้ใส่ LLM_API_KEY ในไฟล์ .env")
    return key


def chat(prompt, system=None, retries=3):
    global call_count
    messages = [{"role": "system", "content": system}] if system else []
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": "qwen3.5",
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": messages,
    }
    headers = {"Authorization": f"Bearer {_api_key()}"}
    for attempt in range(retries):
        try:
            call_count += 1
            r = requests.post(URL, json=payload, headers=headers, timeout=120)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except requests.RequestException:
            if attempt == retries - 1:
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
