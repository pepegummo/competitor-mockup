# Competitor Compare — mock-up

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

เลือกโหมดที่แถบด้านซ้าย:

| โหมด | กรอก | ได้ผล |
|---|---|---|
| เทียบคู่แข่ง (Phase 1) | คู่แข่ง 2–5 ราย | ตาราง กราฟ และรายงานกลาง ๆ |
| เรา vs คู่แข่ง (Phase 2) | บริษัทเรา + คู่แข่ง 2–5 ราย | เพิ่มแท็บ gap (เรา − ค่าเฉลี่ยคู่แข่ง) และรายงานพร้อมข้อเสนอแนะ |

- ข้อมูลดิบ: `data/raw/{company}/{date}.json`
- ฐานข้อมูล: `data/app.db`
- กดซ้ำได้ ข่าวเดิมจะไม่ถูก classify ซ้ำ (ดูจำนวนครั้งที่เรียก LLM ที่แถบสถานะ)
