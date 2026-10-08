# Competitor Compare — mock-up (Step 0 + Phase 1)

ขั้นตอนเต็มอยู่ใน [`docs/mockup-steps.md`](docs/mockup-steps.md)

## ติดตั้ง (Windows / PowerShell)

```powershell
cd competitor-mockup
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

สร้าง `.env` จาก `.env.example` (`copy .env.example .env`) แล้วใส่ key:

```
LLM_API_KEY=ใส่ key ของอาจารย์
```

## ทดสอบ LLM (Step 0.3)

```powershell
python -m core.llm
```

ต้องได้คำทักทายภาษาไทย และ `{'ok': True}`

## รัน

```powershell
streamlit run app.py
```

กรอกชื่อคู่แข่ง 2–5 ราย แล้วกด "เริ่มวิเคราะห์"

- ข้อมูลดิบ: `data/raw/{company}/{date}.json`
- ฐานข้อมูล: `data/app.db`
- กดซ้ำได้ ข่าวเดิมจะไม่ถูก classify ซ้ำ (ดูจำนวนครั้งที่เรียก LLM ที่แถบสถานะ)
