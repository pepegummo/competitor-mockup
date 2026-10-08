# Competitor Compare — ขั้นตอนทำ mock-up

Mock-up นี้รันบนเครื่องตัวเอง ยังไม่ขึ้น Huawei Cloud เป้าหมายคือพิสูจน์ว่า flow
`ดึงข้อมูล → classify → compare → แสดงผล` ทำงานได้จริงกับ LLM ของอาจารย์ ก่อนจะย้ายขึ้น cloud

ทั้ง 3 phase ใช้ pipeline เดียวกัน ต่างกันแค่ "input เริ่มต้น" กับ "มุมมองของการวิเคราะห์"

| Phase | ผู้ใช้กรอก | ระบบทำ | ผลลัพธ์ |
|---|---|---|---|
| 1 | รายชื่อคู่แข่ง | เทียบคู่แข่งกันเอง | ตารางเปรียบเทียบ + รายงานกลาง ๆ |
| 2 | บริษัทเรา + คู่แข่ง | เทียบจากมุมของเรา | จุดที่เรานำ/ตาม + ข้อเสนอแนะ |
| 3 | บริษัทเราอย่างเดียว | หาคู่แข่ง top X เอง แล้วทำแบบ Phase 2 | รายชื่อคู่แข่งพร้อมเหตุผล + ผลแบบ Phase 2 |

ทำตามลำดับ อย่าข้าม เพราะ Phase 2 และ 3 ต่อยอดจากโค้ดของ Phase 1

---

## Step 0 — เตรียมโปรเจ็กต์ (ใช้ร่วมทุก phase)

### 0.1 Stack ของ mock-up

| ส่วน | ใช้ | เหตุผล |
|---|---|---|
| UI | Streamlit | ได้หน้าเว็บ + กราฟ + chat ในไฟล์ Python เดียว |
| ดึงข้อมูล | `feedparser` (RSS), `requests` + `beautifulsoup4` | ไม่ต้องใช้ API key |
| เก็บข้อมูล | SQLite + โฟลเดอร์ `data/raw/` | ไม่ต้องติดตั้ง server |
| LLM | endpoint ของอาจารย์ (`qwen3.5`) | ตามโจทย์ |

### 0.2 โครงสร้างโฟลเดอร์

```
competitor-mockup/
├── .env                # LLM_API_KEY=... (ห้าม commit)
├── .gitignore          # ใส่ .env และ data/
├── requirements.txt
├── app.py              # Streamlit UI
├── core/
│   ├── llm.py          # เรียก LLM
│   ├── db.py           # สร้างตาราง + query
│   ├── collect.py      # ดึงข้อมูล
│   ├── process.py      # classify + extract
│   ├── analyze.py      # compare + เขียนรายงาน
│   └── discover.py     # หาคู่แข่ง (Phase 3)
└── data/
    ├── raw/            # ไฟล์ดิบ
    └── app.db
```

`requirements.txt`

```
streamlit
requests
feedparser
beautifulsoup4
pandas
python-dotenv
```

### 0.3 ทดสอบ LLM ก่อนทำอย่างอื่น

- [ ] รัน curl ของอาจารย์ให้ได้ HTTP 200 และจดเวลาตอบ (`time_total`) ไว้
- [ ] ดูรูปแบบ response ว่าเป็น `choices[0].message.content` หรือไม่ (path `/v1/chat/completions` บอกว่าน่าจะเป็นแบบ OpenAI แต่ต้องดูของจริง)
- [ ] ถามอาจารย์เรื่อง rate limit ต่อกลุ่ม และมี `/v1/embeddings` ไหม (ใช้ตอนทำ chat)

`core/llm.py`

```python
import os, re, json, time, requests
from dotenv import load_dotenv

load_dotenv()
URL = "https://llm.nattee.net/v1/chat/completions"

def chat(prompt, system=None, retries=3):
    messages = [{"role": "system", "content": system}] if system else []
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": "qwen3.5",
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": messages,
    }
    headers = {"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"}
    for attempt in range(retries):
        try:
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
```

- [ ] เรียก `chat("Say hello in Thai")` ได้คำตอบ
- [ ] เรียก `chat_json('Return only JSON: {"ok": true}')` แล้ว parse ผ่าน

### 0.4 ตารางใน SQLite

```sql
CREATE TABLE companies (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE,
  role TEXT,            -- 'self' | 'competitor'
  website TEXT,
  origin TEXT           -- 'user' | 'discovered'
);

CREATE TABLE documents (
  id INTEGER PRIMARY KEY,
  company_id INTEGER REFERENCES companies(id),
  source_type TEXT,     -- 'news' | 'website'
  url TEXT,
  title TEXT,
  published_at TEXT,
  content_hash TEXT UNIQUE,   -- กันข้อมูลซ้ำ
  raw_path TEXT,
  fetched_at TEXT
);

CREATE TABLE facts (
  id INTEGER PRIMARY KEY,
  document_id INTEGER REFERENCES documents(id),
  company_id INTEGER REFERENCES companies(id),
  category TEXT,
  sentiment TEXT,       -- 'positive' | 'neutral' | 'negative'
  summary TEXT,
  data_json TEXT        -- ข้อมูลที่สกัดเพิ่ม เช่น ราคา
);

CREATE TABLE reports (
  id INTEGER PRIMARY KEY,
  mode TEXT,            -- 'phase1' | 'phase2' | 'phase3'
  created_at TEXT,
  content_md TEXT
);
```

- [ ] เขียน `db.py` ให้มี `init_db()`, `upsert_company()`, `insert_document()` (ข้ามถ้า hash ซ้ำ), `insert_fact()`

---

## Phase 1 — เลือกแค่คู่แข่ง

**Input:** ชื่อคู่แข่ง 2–5 ราย (ใส่ URL เว็บไซต์เพิ่มได้ แต่ไม่บังคับ)
**Output:** ตาราง + กราฟเปรียบเทียบ และรายงานสรุปที่ไม่เข้าข้างใคร

### 1.1 หน้า input

- [ ] `app.py`: ช่องกรอกชื่อบริษัททีละบรรทัด + ปุ่ม "เริ่มวิเคราะห์"
- [ ] บันทึกลง `companies` ด้วย `role='competitor'`, `origin='user'`

### 1.2 ดึงข้อมูล (`collect.py`)

เริ่มจากข่าวอย่างเดียวก่อน เพราะใช้ได้กับทุกบริษัทโดยไม่ต้องเขียน parser เฉพาะเว็บ

```python
import feedparser, urllib.parse

def fetch_news(company, lang="th", country="TH", limit=20):
    q = urllib.parse.quote(company)
    url = (f"https://news.google.com/rss/search?q={q}"
           f"&hl={lang}&gl={country}&ceid={country}:{lang}")
    feed = feedparser.parse(url)
    return [
        {"title": e.title, "url": e.link, "published": e.get("published", "")}
        for e in feed.entries[:limit]
    ]
```

- [ ] ดึงข่าว 20 หัวข้อต่อบริษัท
- [ ] บันทึก JSON ดิบลง `data/raw/{company}/{date}.json`
- [ ] hash จาก `title + url` แล้ว insert ลง `documents` (ซ้ำให้ข้าม)
- [ ] ทดสอบ: กดรันซ้ำ 2 ครั้ง จำนวนแถวต้องไม่เพิ่ม

> RSS ให้แค่หัวข้อข่าวกับแหล่งที่มา ไม่มีเนื้อหาเต็ม สำหรับ mock-up ถือว่าพอ
> ถ้าต้องการเนื้อหาเต็มค่อยเพิ่มการดึงหน้าเว็บทีหลัง

### 1.3 Classify (`process.py`)

ส่งทีละ 10 หัวข้อต่อ 1 call เพื่อประหยัดจำนวนครั้งที่เรียก LLM

```
You are a business analyst. Classify each news headline about a company.

Categories: product_price, promotion, news_pr, review, financial, hr, other
Sentiment (toward the company): positive, neutral, negative

Return ONLY a JSON array, one object per headline:
[{"id": <id>, "category": "...", "sentiment": "...", "summary": "<สรุปภาษาไทย 1 ประโยค>"}]

Company: {company}
Headlines:
{id}: {title}
...
```

- [ ] วนเฉพาะ `documents` ที่ยังไม่มีใน `facts`
- [ ] ตรวจผลลัพธ์: `id` ต้องตรงกับที่ส่งไป, `category` ต้องอยู่ในรายการ ถ้าไม่ผ่านให้ลองใหม่ 1 ครั้ง แล้วค่อยข้าม
- [ ] บันทึกลง `facts`

### 1.4 Compare (`analyze.py`)

ตัวเลขทั้งหมดคิดด้วย SQL/pandas ไม่ให้ LLM นับเอง

- [ ] ตาราง A: จำนวนข่าวต่อ `บริษัท × category`
- [ ] ตาราง B: สัดส่วน sentiment ต่อบริษัท
- [ ] ตาราง C: ข่าวล่าสุด 5 รายการต่อบริษัท (ใช้ `summary`)

### 1.5 รายงานโดย LLM

```
You are a market analyst. Using ONLY the data below, write a comparison
of these companies in Thai (markdown, under 300 words).
Cover: what each company is focusing on, who gets the most positive/negative
coverage, and notable recent moves. Do not invent facts or numbers.

[Table A]
[Table B]
[Table C]
```

- [ ] บันทึกลง `reports` ด้วย `mode='phase1'`

### 1.6 หน้าแสดงผล

- [ ] ตาราง A + bar chart (`st.bar_chart`)
- [ ] sentiment ต่อบริษัท
- [ ] รายงาน (`st.markdown`)
- [ ] รายการข่าวพร้อม link ให้คลิกตรวจได้

### เสร็จ Phase 1 เมื่อ

- [ ] กรอกชื่อ 3 บริษัท กดปุ่มเดียว ได้ตาราง กราฟ และรายงาน
- [ ] ตัวเลขในรายงานตรงกับตาราง
- [ ] รันซ้ำแล้วไม่เรียก LLM ซ้ำกับข่าวเดิม

---

## Phase 2 — บอกบริษัทเรา + คู่แข่ง

**Input:** ชื่อบริษัทเรา 1 ราย + คู่แข่ง 2–5 ราย
**Output:** เหมือน Phase 1 แต่ทุกอย่างมองจากมุมของบริษัทเรา

สิ่งที่เปลี่ยนจาก Phase 1 มีแค่ 3 จุด

### 2.1 Input

- [ ] เพิ่มช่อง "บริษัทของเรา" แยกจากช่องคู่แข่ง
- [ ] บันทึกด้วย `role='self'`
- [ ] ดึงข้อมูลและ classify บริษัทเราด้วย pipeline เดิม (ไม่ต้องแก้ `collect.py` และ `process.py`)

### 2.2 Compare แบบมี "เรา" เป็นจุดอ้างอิง

- [ ] ตาราง gap: ค่าของเรา ลบ ค่าเฉลี่ยคู่แข่ง ในแต่ละ category และ sentiment
- [ ] ในกราฟ ให้แถวของเราเด่นกว่าแถวอื่น

### 2.3 Prompt รายงานเปลี่ยนมุมมอง

```
You are a strategy advisor for {self_company}. Using ONLY the data below,
write in Thai (markdown, under 400 words):
1. Where {self_company} is ahead of competitors
2. Where it is behind
3. Threats: recent competitor moves that could hurt us
4. Opportunities: gaps no competitor is covering
5. 3 recommended actions, each tied to a specific data point
Do not invent facts or numbers.

[Table A] [Table B] [Table C] [Gap table]
```

- [ ] บันทึกด้วย `mode='phase2'`

### เสร็จ Phase 2 เมื่อ

- [ ] รายงานพูดถึงบริษัทเราในทุกหัวข้อ
- [ ] ข้อเสนอแนะแต่ละข้ออ้างถึงข้อมูลที่มีอยู่จริงในตาราง
- [ ] Phase 1 ยังใช้งานได้ (ถ้าไม่กรอกบริษัทเรา ระบบทำงานแบบ Phase 1)

---

## Phase 3 — บอกแค่บริษัทเรา ให้ระบบหาคู่แข่งเอง

**Input:** ชื่อบริษัทเรา + จำนวน top X (เช่น slider 3–10) + คำใบ้ optional (อุตสาหกรรม, ประเทศ)
**Output:** รายชื่อคู่แข่งพร้อมเหตุผลและหลักฐาน → ผู้ใช้ยืนยัน → ผลแบบ Phase 2

### 3.1 เลือกวิธีหาคู่แข่ง (`discover.py`)

| วิธี | ทำอย่างไร | ข้อดี | ข้อเสีย |
|---|---|---|---|
| A) ถาม LLM ตรง ๆ | "ใครคือคู่แข่งของ X" | เร็ว 1 call | อาจแต่งชื่อขึ้นมา ข้อมูลอาจเก่า ไม่รู้จักบริษัทเล็ก |
| B) หาจากข่าว | ค้นข่าว แล้วให้ LLM ดึงชื่อบริษัทที่ถูกพูดถึง | มีหลักฐานอ้างอิง | ได้เฉพาะบริษัทที่เป็นข่าว |
| C) ผสม A + B | รวมรายชื่อจากทั้งสองทาง แล้วจัดอันดับ | ครอบคลุมและตรวจสอบได้ | เรียก LLM มากกว่า |

แนะนำ C โดยทำ A ให้เสร็จก่อน แล้วค่อยเพิ่ม B

### 3.2 ขั้นตอนของวิธี C

- [ ] **หา candidate จาก LLM:**

```
List up to {2X} direct competitors of "{company}" in {country}.
Industry hint: {industry or "unknown"}.
Return ONLY JSON: [{"name": "...", "reason": "<เหตุผลภาษาไทย 1 ประโยค>"}]
If you do not know this company, return [].
```

- [ ] **หา candidate จากข่าว:** ใช้ `fetch_news()` กับคำค้น เช่น `"{company} คู่แข่ง"`, `"{company} competitors"`, `"{industry} ส่วนแบ่งตลาด"` แล้วให้ LLM ดึงชื่อบริษัทอื่นที่ปรากฏในหัวข้อข่าว
- [ ] **รวมรายชื่อ:** รวมชื่อซ้ำ/ชื่อย่อให้เป็นรายเดียว ตัดบริษัทเราและบริษัทในเครือออก
- [ ] **ตรวจว่ามีตัวตน:** candidate แต่ละรายต้องค้นข่าวเจออย่างน้อย 1 รายการ ถ้าไม่เจอให้ติดป้าย "ไม่พบหลักฐาน"
- [ ] **จัดอันดับ:** ให้คะแนนจาก (ก) มาจากทั้งสองทางหรือทางเดียว (ข) จำนวนครั้งที่ถูกพูดถึงคู่กับเรา แล้วตัดเหลือ top X

### 3.3 ให้ผู้ใช้ยืนยันก่อนเสมอ

- [ ] แสดงรายชื่อเป็น checkbox พร้อมเหตุผล หลักฐาน (link ข่าว) และป้าย "ไม่พบหลักฐาน"
- [ ] ผู้ใช้ติ๊กออก หรือพิมพ์เพิ่มเองได้
- [ ] กดยืนยัน → บันทึกด้วย `origin='discovered'` → เรียก pipeline ของ Phase 2

> ขั้นยืนยันนี้ห้ามตัด เพราะถ้ารายชื่อคู่แข่งผิด ผลวิเคราะห์ทั้งหมดที่ตามมาจะผิดไปด้วย

### เสร็จ Phase 3 เมื่อ

- [ ] ทดสอบกับบริษัทที่รู้คำตอบอยู่แล้ว 2–3 ราย แล้วรายชื่อที่ได้สมเหตุสมผล
- [ ] ทดสอบกับชื่อบริษัทที่ไม่มีจริง ระบบต้องบอกว่าหาไม่เจอ ไม่ใช่แต่งรายชื่อขึ้นมา
- [ ] หลังยืนยันรายชื่อ ได้ผลลัพธ์แบบเดียวกับ Phase 2

---

## สิ่งที่ mock-up นี้ยังไม่ทำ (เก็บไว้ทำตอนขึ้น cloud)

| ใน mock-up | ตอนขึ้น cloud จะเปลี่ยนเป็น |
|---|---|
| กดปุ่มเพื่อรัน | timer รันอัตโนมัติรายวัน/รายสัปดาห์ |
| วน loop เรียก LLM ทีละชุด | queue + worker ที่คุม rate limit |
| `data/raw/` บนเครื่อง | object storage |
| SQLite | managed relational database |
| ข่าวอย่างเดียว | เพิ่มราคา รีวิว และงบการเงิน |
| ยังไม่มี | chat (RAG) และ alert |

## ลำดับที่แนะนำ

1. Step 0 ให้ LLM ตอบ JSON ได้เสถียรก่อน เพราะทุก phase พึ่งส่วนนี้
2. Phase 1 ทำให้จบทั้งเส้นด้วย 2 บริษัทก่อน แล้วค่อยขัดเกลา
3. Phase 2 เป็นการแก้ prompt และตารางเป็นหลัก ใช้เวลาน้อยที่สุด
4. Phase 3 ใช้เวลามากที่สุดที่การรวมชื่อซ้ำและการทดสอบ
