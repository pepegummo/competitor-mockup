# แผนขึ้น Huawei Cloud

แบบสำหรับ **เดโม/ส่งงาน**: ผู้ใช้ไม่กี่คน (ทีม + อาจารย์) เน้นถูกและดูแลง่าย ทุกอย่างรันเป็น Docker บนเครื่อง ECS เครื่องเดียว
ฐานข้อมูลแยกไปใช้ RDS PostgreSQL + pgvector · LLM ยังใช้ endpoint ของอาจารย์ · embedding (e5) รันใน container
ภาพรวมของระบบตอนนี้ดู [`architecture.md`](architecture.md)

> **สถานะ:** เป็นแบบ ยังไม่ได้สร้างจริง และโค้ดยังต้องแก้ตาม [สิ่งที่ต้องแก้ในโค้ด](#สิ่งที่ต้องแก้ในโค้ดก่อนขึ้นจริง) ก่อน

**Region:** AP-Bangkok (`ap-southeast-2`) ข้อมูลอยู่ในไทย และใกล้ผู้ใช้/แหล่งข่าวไทย

## แผนภาพ

```mermaid
flowchart LR
    USER["ผู้ใช้<br/>เบราว์เซอร์"] -->|"HTTPS + รหัสผ่าน"| EIP["EIP"]
    subgraph VPC["VPC · AP-Bangkok"]
        subgraph ECS["ECS · Docker Compose"]
            PROXY["proxy<br/>Caddy: HTTPS + basic auth"]
            WEB["web<br/>Streamlit app.py"]
            WORKER["worker<br/>cron รายวัน + หยิบงานจากตาราง jobs"]
            OCR["ocr<br/>Tesseract tha + pymupdf"]
            PROXY --> WEB
            WEB -->|"PDF ที่อัปโหลด"| OCR
        end
        RDS[("RDS for PostgreSQL<br/>+ pgvector<br/>subnet ส่วนตัว")]
        WEB --> RDS
        WORKER --> RDS
    end
    EIP --> PROXY
    WEB --> OBS[("OBS<br/>ไฟล์ดิบ · ไฟล์อัปโหลด · รายงาน")]
    WORKER --> OBS
    SWR["SWR<br/>Docker image"] -.->|"docker pull"| ECS
    WORKER -->|"ผ่าน EIP"| EXT["ภายนอก<br/>LLM อาจารย์ · Google News · RSS<br/>SET · App Store/Play · webhook"]
    WEB -->|"ผ่าน EIP"| EXT
    CE["Cloud Eye"] -.->|"เฝ้าดู"| ECS
    CE -.->|"เฝ้าดู"| RDS
```

ทุกอย่างวิ่งออกเน็ตผ่าน EIP ของ ECS (เรียก LLM ดึงข่าว ส่งแจ้งเตือน) จึงไม่ต้องใช้ NAT Gateway
RDS ไม่มี IP สาธารณะ รับการเชื่อมต่อจาก ECS เท่านั้น

## รายการ service

| Service | ใช้ทำอะไร | ขนาดสำหรับเดโม |
|---|---|---|
| **VPC + Subnet + Security Group** | เครือข่ายส่วนตัว · SG ของ ECS เปิดแค่ 80/443 (และ 22 เฉพาะ IP ทีม) · SG ของ RDS รับ 5432 จาก SG ของ ECS เท่านั้น | – |
| **ECS** | รัน Docker Compose ทั้งหมด | 4 vCPU / 8 GB (torch + โมเดล e5 + Streamlit + งานวิเคราะห์) · Ubuntu 22.04 · ดิสก์ EVS 40 GB |
| **EIP + Bandwidth** | IP สาธารณะ: รับผู้ใช้ และออกไป LLM/แหล่งข่าว | ~5 Mbit/s คิดตาม traffic |
| **RDS for PostgreSQL** | แทน SQLite ทุกตาราง · extension `pgvector` เก็บเวกเตอร์และค้นความใกล้ | single instance 2 vCPU / 4 GB · ดิสก์ 40 GB · backup อัตโนมัติ 7 วัน |
| **OBS** | ไฟล์ดิบ (`data/raw`) · ไฟล์ที่อัปโหลด (CSV/Excel/PDF) · รายงาน .docx | Standard bucket ส่วนตัว |
| **SWR** | เก็บ Docker image ส่วนตัว: build บนเครื่องเรา → push → ECS pull | organization เดียว |
| **Cloud Eye** | กราฟและแจ้งเตือน CPU / RAM / ดิสก์ ของ ECS และ RDS | ค่าเริ่มต้น + alarm ดิสก์ > 80% |
| DEW / CSMS (ไม่บังคับ) | เก็บ `LLM_API_KEY` รหัส DB และ webhook แทนไฟล์ `.env` | เดโมใช้ `.env` บน ECS (`chmod 600`) ได้ |
| OCR ของ Huawei (ทางเลือก) | ถ้า General Text OCR รองรับภาษาไทย ใช้แทน container `ocr` ได้ | ต้องทดสอบกับ PDF ไทยก่อน |
| DNS (ไม่บังคับ) | ชื่อโดเมนสำหรับ HTTPS · ไม่มีโดเมนใช้ `<EIP>.sslip.io` ได้ | – |

ไม่ใช้ในรอบเดโม (ค่อยเพิ่มเมื่อผู้ใช้มากขึ้น): CCE (Kubernetes) · ELB · DMS (queue) · NAT Gateway · ModelArts

## Containers

ใช้ image แอปเดียว (`competitor-app`) สำหรับทั้ง `web` และ `worker` ต่างกันแค่คำสั่งที่รัน

| Container | Image | หน้าที่ | พอร์ต |
|---|---|---|---|
| `proxy` | `caddy:2` | HTTPS (Let's Encrypt อัตโนมัติ) + basic auth · ส่งต่อ websocket ของ Streamlit | 80, 443 ออกนอก |
| `web` | `competitor-app` | `streamlit run app.py` | 8501 ภายในเท่านั้น |
| `worker` | `competitor-app` | cron (supercronic) รัน `monitor.py` ทุกวัน · วนอ่านตาราง `jobs` ที่รออยู่แล้วรัน `monitor.py --job <id>` | – |
| `ocr` (profile `ocr`) | `competitor-ocr` (build จาก `ocr/`) | `POST /extract` รับ PDF คืนข้อความทีละหน้า: ใช้ข้อความในไฟล์ก่อน OCR (Tesseract `tha+eng`) เฉพาะหน้าที่เป็นภาพหรือข้อความเพี้ยน | 8000 ภายในเท่านั้น |

**image `competitor-app`:** `python:3.12-slim` + torch แบบ CPU + `requirements.txt` + โมเดล `intfloat/multilingual-e5-small`
ดาวน์โหลดฝังไว้ตอน build (container ไม่ต้องโหลดโมเดลตอนเริ่ม และรันได้แม้ Hugging Face ล่ม) ขนาดราว 2–2.5 GB

**config ผ่าน env (ไฟล์ `.env` บน ECS):**

| ตัวแปร | ค่า |
|---|---|
| `LLM_API_KEY` | key ของอาจารย์ |
| `DATABASE_URL` | `postgresql://app:<รหัส>@<IP ส่วนตัวของ RDS>:5432/competitor` |
| `OBS_ENDPOINT`, `OBS_BUCKET`, `OBS_AK`, `OBS_SK` | ที่เก็บไฟล์ (หรือใช้ agency ของ ECS แทน AK/SK) |
| `EMBED_BACKEND` | `local` |
| `ALERT_WEBHOOK_URL` | ไม่บังคับ |
| `MONITOR_AT` | เวลารันอัตโนมัติ เช่น `07:00` (เวลาไทย) |
| `OCR_URL` | `http://ocr:8000` เมื่อเปิด profile `ocr` (เว้นว่าง = อ่านเฉพาะ PDF ที่มีข้อความในไฟล์) |
| `BASIC_AUTH_USER`, `BASIC_AUTH_HASH` | รหัสเข้าเว็บของ Caddy (`caddy hash-password`) |

ร่าง `docker-compose.yml` (ยังไม่ได้สร้างไฟล์จริง):

```yaml
services:
  proxy:
    image: caddy:2
    ports: ["80:80", "443:443"]
    volumes: ["./Caddyfile:/etc/caddy/Caddyfile:ro", "caddy_data:/data"]
    env_file: .env
    depends_on: [web]
    restart: unless-stopped
  web:
    image: swr.ap-southeast-2.myhuaweicloud.com/<org>/competitor-app:<tag>
    command: streamlit run app.py --server.address=0.0.0.0 --server.port=8501
    env_file: .env
    restart: unless-stopped
  worker:
    image: swr.ap-southeast-2.myhuaweicloud.com/<org>/competitor-app:<tag>
    command: python worker.py   # cron รายวัน + หยิบงานจากตาราง jobs
    env_file: .env
    restart: unless-stopped
  ocr:
    image: swr.ap-southeast-2.myhuaweicloud.com/<org>/competitor-ocr:<tag>
    profiles: ["ocr"]           # เปิดด้วย docker compose --profile ocr up -d
    deploy:
      resources:
        limits: { cpus: "1.5", memory: 1.5g }   # OCR ใช้ CPU เต็มตอนมีไฟล์ จำกัดไว้ไม่ให้หน้าเว็บช้า
    restart: unless-stopped
volumes:
  caddy_data:
```

## สิ่งที่ต้องแก้ในโค้ดก่อนขึ้นจริง

| # | ไฟล์ | ต้องแก้ |
|---|---|---|
| 1 | `core/db.py` | SQLite → PostgreSQL (psycopg): `?` → `%s` · `INSERT OR REPLACE` → `ON CONFLICT` · ตัด `PRAGMA` / `executescript` / `sqlite3.Row` · `INTEGER PRIMARY KEY` → `bigserial` · `MIGRATIONS` ใช้ `ADD COLUMN IF NOT EXISTS` · `CREATE EXTENSION vector` |
| 2 | `core/embed.py`, `core/ask.py` | ตาราง `embeddings.vec` เป็น `vector(384)` · ค้นด้วย `ORDER BY vec <=> :q` (cosine) แทน numpy · โมเดลยังรันใน container |
| 3 | `core/collect.py`, `core/internal.py` | `RAW_DIR` / `raw_path` และ PDF ต้นฉบับ (`data/uploads/`, `save_pdf`) เขียนไป OBS (หรือ volume ก่อนในรอบแรก) |
| 4 | `ui/watch_panel.py`, `app.py` | ตัด `schtasks` (ใช้ได้แค่ Windows) และ `subprocess.Popen` · ปุ่ม "เริ่มวิเคราะห์"/"รันตอนนี้" แค่สร้างแถวใน `jobs` สถานะ `queued` ให้ worker หยิบ · เวลารันรายวันมาจาก `MONITOR_AT` |
| 5 | ใหม่ `worker.py` | วนทุก 5 วินาที: หยิบงาน `queued` (ใช้ `SELECT … FOR UPDATE SKIP LOCKED`) → รัน `pipeline.run` · ถึงเวลา `MONITOR_AT` → รันชุดติดตามทั้งหมดเหมือน `monitor.py` |
| 6 | ใหม่ `Dockerfile`, `docker-compose.yml`, `Caddyfile`, `.dockerignore` | `.dockerignore` ต้องตัด `.env`, `data/`, `.venv/`, `.git/` |
| 7 | ใหม่ สคริปต์ย้ายข้อมูล | copy `data/app.db` (และ `demo/app.db` ถ้าจะใช้โหมดเดโมบน cloud) → PostgreSQL ครั้งเดียว |
| 8 | OCR | **ทำแล้ว** สำหรับ PDF ที่อัปโหลดในหน้าข้อมูลภายใน: `ocr/` (FastAPI + pymupdf + Tesseract) เรียกผ่าน `core/ocr.py` ตาม `OCR_URL` · ที่ยังไม่ทำ: ข่าวที่ลิงก์เป็น PDF และงบการเงินจาก SET |

ตาราง `jobs` มี `status` อยู่แล้ว (`running` / `done` / `error`) จึงใช้เป็น queue ได้ แค่เพิ่มสถานะ `queued` ไม่ต้องใช้ DMS

## ขั้นตอน deploy

1. สร้าง VPC + subnet + Security Group 2 ชุด (ECS, RDS)
2. สร้าง RDS for PostgreSQL ใน subnet ส่วนตัว → `CREATE EXTENSION vector;` → สร้าง user/database ของแอป
3. สร้าง OBS bucket ส่วนตัว
4. สร้าง ECS + EIP → ลง Docker + compose plugin → เปิด Cloud Eye agent
5. บนเครื่องเรา: `docker build` 2 image (`competitor-app` จากโฟลเดอร์หลัก · `competitor-ocr` จาก `ocr/`) → `docker push` ไป SWR
6. บน ECS: วาง `.env` (มี `OCR_URL=http://ocr:8000`), `docker-compose.yml`, `Caddyfile` → `docker compose --profile ocr up -d`
   (ไม่ใช้ OCR: `docker compose up -d` และเว้น `OCR_URL` ว่าง)
7. รันสคริปต์ย้ายข้อมูลจาก SQLite (ครั้งเดียว)
8. ตั้ง DNS (หรือใช้ `<EIP>.sslip.io`) → เปิด `https://…` ใส่รหัส → กดวิเคราะห์ 1 รอบ และถาม 1 คำถาม

## ค่าใช้จ่ายโดยประมาณ

เดโมไม่ต้องเปิดตลอด เลือกแบบ **pay-per-use** แล้วปิด ECS/RDS เมื่อไม่ใช้
ราคาจริงขึ้นกับ region และโปรโมชัน ให้คำนวณด้วย Pricing Calculator ของ Huawei Cloud ก่อนสร้าง
(ส่วนที่แพงสุดคือ ECS 4 vCPU / 8 GB และ RDS ส่วน OBS, SWR, Cloud Eye เกือบไม่มีค่าใช้จ่ายที่ขนาดนี้)
ถ้างบจำกัด: ลด ECS เหลือ 2 vCPU / 4 GB ได้ แต่คำถามแรกหลังเปิดเครื่อง (โหลดโมเดล) และการคำนวณเวกเตอร์จะช้าลง

## ต้องตรวจใน console ก่อนสร้าง

ค้นเอกสารแล้วยังยืนยันไม่ได้:

- **RDS for PostgreSQL ใน AP-Bangkok เปิด `pgvector` ได้ไหม และรุ่นไหน** เอกสาร Huawei ที่พบระบุ PG 12–14 (หน้าอาจเก่า)
  ตรวจด้วย `SELECT name FROM pg_available_extensions WHERE name = 'vector';`
  ถ้าไม่มี: รัน PostgreSQL + pgvector เป็น container บน ECS แทน (image `pgvector/pgvector`) + สำรองข้อมูลไป OBS
- **SWR มีใน AP-Bangkok ไหม** ถ้าไม่มี ใช้ SWR region ใกล้สุด หรือ build image บน ECS ตรง ๆ
- **General Text OCR ของ Huawei รองรับภาษาไทยไหม** ที่ยืนยันได้มีแค่บัตรประชาชนไทยและป้ายทะเบียนไทยใน AP-Bangkok
  ถ้าไม่รองรับ ใช้ container `ocr` (Tesseract) ตามแบบ
- **endpoint ของอาจารย์รับ request จาก IP ของ Huawei Cloud ไหม** (บางเครื่องจำกัด IP)

## ขยายเมื่อผู้ใช้มากขึ้น

| ตอนนี้ | ขยายเป็น |
|---|---|
| ECS เครื่องเดียว + Compose | CCE (Kubernetes) ใช้ image เดิม แยก `web` หลาย replica + ELB |
| ตาราง `jobs` เป็น queue | DMS (Kafka/RabbitMQ) เมื่อ worker หลายเครื่อง |
| e5 ใน container | embedding API (ตั้ง `EMBED_BACKEND=api`) หรือ ModelArts |
| basic auth | ระบบ login จริง (เช่น IAM/OIDC ผ่าน proxy) |
| RDS single | RDS แบบ primary/standby |
