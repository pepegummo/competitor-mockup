# คู่มือขึ้นระบบบน Huawei Cloud

คู่มือเล่มเดียวตั้งแต่สร้างเครื่องใน console จนเปิดเว็บได้ ทำตามลำดับขั้นที่ 1–9 ได้เลย
ไม่ต้อง clone โค้ด ไม่ต้องลง Python ใช้แค่ Docker · image อยู่บน Docker Hub (`quix07/competitor-app`, `quix07/competitor-ocr`) รุ่นปัจจุบัน **0.5**

## ภาพรวม

```
ผู้ใช้ ──HTTPS──▶ EIP ──▶ ECS (Docker Compose)
                          ├─ proxy   Caddy: HTTPS อัตโนมัติ + รหัสเข้าเว็บ (ไม่บังคับ)   พอร์ต 80/443 ออกนอก
                          ├─ web     หน้าเว็บ Streamlit                                  8501 ภายใน
                          ├─ worker  รันงานวิเคราะห์ที่กดจากเว็บ + รันชุดติดตามทุกวันตาม MONITOR_AT
                          ├─ ocr     อ่าน PDF สแกนภาษาไทย (Tesseract)                    8000 ภายใน
                          ├─ db      PostgreSQL + pgvector (เฉพาะแบบ container db)        5432 ภายใน
                          └─ volume app_data: ข้อมูลดิบที่ดึงมา · PDF ที่อัปโหลด · log
                          │
                          └──▶ RDS for PostgreSQL + pgvector (เฉพาะแบบ RDS · subnet ส่วนตัว)
ECS ──ผ่าน EIP──▶ ภายนอก: LLM ของอาจารย์ · Google News · RSS · SET · App Store/Play
```

`web` กับ `worker` ใช้ image เดียวกัน (`competitor-app`) · ทุกอย่างออกเน็ตผ่าน EIP ของ ECS จึงไม่ต้องใช้ NAT Gateway

## เตรียมก่อนเริ่ม

**1. ของที่ต้องได้จากเจ้าของโปรเจกต์** (ไม่อยู่ใน image)

- `LLM_API_KEY` (key ของอาจารย์): ขอทางช่องทางส่วนตัว ใส่ใน `.env` บนเซิร์ฟเวอร์เท่านั้น ห้ามใส่ใน git หรือ image
- `app.db` ถ้าต้องการข้อมูลที่วิเคราะห์ไว้แล้ว (ไม่มีก็เริ่มจากฐานข้อมูลว่างได้)

**2. เลือกฐานข้อมูล 1 แบบ** (ทุกขั้นด้านล่างแยกให้ว่าแบบไหนทำอะไร)

| แบบ | เหมาะกับ | ข้อเสีย |
|---|---|---|
| **RDS for PostgreSQL** | ใช้งานจริง: backup อัตโนมัติ ไม่ต้องดูแลเอง | มีค่าใช้จ่ายเพิ่ม · ต้องตรวจว่าเปิด `pgvector` ได้ (ขั้นที่ 1) |
| **container `db`** บน ECS | เดโม / ยังไม่มี RDS: ถูกกว่า ตั้งง่ายกว่า | ข้อมูลอยู่บนดิสก์ ECS เครื่องเดียว ต้องสำรองเอง |

(ถ้าไม่ตั้งฐานข้อมูลเลย แอปจะใช้ SQLite ใน volume ได้ เหมาะแค่ลองเร็ว ๆ)

## สเปกทั้งหมด

### Resource บน Huawei Cloud

| รายการ | สเปก | หมายเหตุ |
|---|---|---|
| Region | AP-Bangkok (`ap-southeast-2`) | ข้อมูลอยู่ในไทย · คิดเงินแบบ **pay-per-use** แล้วปิด ECS/RDS ตอนไม่ใช้ |
| **ECS** CPU | **x86_64 เท่านั้น** | image เป็น `linux/amd64` · แบบ Kunpeng (ARM) ใช้ไม่ได้ |
| ECS ขนาด | **4 vCPU / 8 GiB** (แนะนำ) · ขั้นต่ำ 2 vCPU / 4 GiB | flavor ตัวอย่าง: General computing `s6.xlarge.2` (4/8) หรือ `s6.large.2` (2/4) · อยากได้ CPU ไม่แชร์: `c6s.xlarge.2` · ชื่อรุ่นในแต่ละ region อาจต่างกัน เลือกที่ vCPU/RAM ตรง |
| ECS OS | Ubuntu 22.04 server 64bit (public image) | Ubuntu 24.04 ก็ได้ |
| ECS ดิสก์ | System disk **40 GB** แบบ General Purpose SSD | image ทั้งหมดใช้ ~4.7 GB · ที่เหลือเป็นข้อมูล log และพื้นที่ตอนอัปเดตรุ่น |
| **EIP** | Dynamic BGP · bandwidth ~5 Mbit/s คิดตาม traffic | ผูกกับ ECS · ใช้ทั้งรับผู้ใช้และออกเน็ต |
| **VPC** | 1 VPC + subnet ส่วนตัว | ECS และ RDS อยู่ VPC เดียวกัน |
| **Security Group ECS** | Inbound: TCP 80, 443 จาก `0.0.0.0/0` · TCP 22 จาก IP ทีมเท่านั้น · Outbound: อนุญาตทั้งหมด (ค่าเริ่ม) | ต้องออก HTTPS ได้ทุกที่ เพราะแอปดึงเนื้อข่าวจากเว็บข่าวหลายโดเมน |
| **RDS** (เฉพาะแบบ RDS) | RDS for PostgreSQL · **16** ถ้ามี (ตรงกับ container `db`) อย่างน้อย 14 · single instance 2 vCPU / 4 GiB · ดิสก์ 40 GB SSD · backup อัตโนมัติ 7 วัน | subnet ส่วนตัว ไม่มี IP สาธารณะ · ต้องเปิด extension `vector` ได้ (ตรวจในขั้นที่ 3) |
| **Security Group RDS** | Inbound: TCP 5432 จาก **Security Group ของ ECS** เท่านั้น | |
| Snapshot / Cloud Eye | snapshot ดิสก์ ECS เป็นประจำ · Cloud Eye ไม่บังคับ (alarm ดิสก์ > 80%) | volume `app_data` และฐานข้อมูลแบบ container `db` อยู่บนดิสก์ ECS |
| โดเมน | ไม่บังคับ · ไม่มีใช้ `<EIP แบบขีด>.sslip.io` ได้ HTTPS เหมือนกัน | |

### ซอฟต์แวร์และ image

| รายการ | รุ่น | ขนาด (ดาวน์โหลด / บนดิสก์) |
|---|---|---|
| Docker Engine + **Compose plugin** | Compose **2.20 ขึ้นไป** (ติดตั้งด้วย `get.docker.com` ได้รุ่นล่าสุดอยู่แล้ว) | – |
| `quix07/competitor-app` (web + worker) | `0.5` · Python 3.12 · torch CPU · โมเดล `intfloat/multilingual-e5-small` ฝังใน image | ~840 MB / 3.5 GB |
| `quix07/competitor-ocr` | `0.5` · FastAPI + Tesseract `tha+eng` | ~124 MB / 490 MB |
| `caddy` (proxy) | `2` · HTTPS อัตโนมัติจาก Let's Encrypt | ~24 MB / 93 MB |
| `pgvector/pgvector` (เฉพาะแบบ container `db`) | `pg16` | ~150 MB / 620 MB |

### การใช้ทรัพยากร (วัดจริงด้วย 0.3 ชุดข้อมูลเดโม 44 บริษัท)

| สถานะ | RAM | หมายเหตุ |
|---|---|---|
| เปิดรอเฉย ๆ (ทุก container) | ~230 MB | เว็บพร้อมใช้ภายใน ~15 วินาทีหลัง `up -d` |
| ระหว่างถามข้อมูล / วิเคราะห์ | **~1 GB ต่อ process** ที่โหลดโมเดล e5 (web และ worker โหลดแยกกัน) | คำนวณเวกเตอร์ข่าว 300 รายการ ~15 วินาที (ครั้งแรก ครั้งต่อไปใช้ cache ใน DB) |
| `ocr` | จำกัดไว้ที่ 1.5 CPU / 1.5 GB | PDF สแกน ~1–2 วินาทีต่อหน้า |
| `db` | ~70 MB | ฐานข้อมูลเดโม ~11 MB |

รวมช่วงใช้งานหนักราว 3–4 GB จึงแนะนำ 8 GiB (4 GiB ใช้ได้แต่ตึง)

### พอร์ต

| พอร์ต | container | เปิดให้ใคร |
|---|---|---|
| 80, 443 | `proxy` | ทุกที่ (ผ่าน EIP) · 80 ใช้ขอใบรับรอง HTTPS และ redirect |
| 8501 | `web` | ภายใน compose เท่านั้น (ผ่าน proxy) |
| 8000 | `ocr` | ภายใน compose เท่านั้น |
| 5432 | `db` / RDS | ภายใน compose / ECS → RDS เท่านั้น |
| 22 | SSH ของ ECS | IP ทีมเท่านั้น |

### ปลายทางที่เซิร์ฟเวอร์ต้องออกไปถึง (HTTPS)

| ปลายทาง | ใช้ทำอะไร |
|---|---|
| `llm.nattee.net` | LLM ของอาจารย์ (ต้องรับ IP ของ Huawei Cloud) |
| `news.google.com` + เว็บข่าวต้นทาง (หลายโดเมน) | ดึงข่าวและเนื้อข่าว |
| `www.set.or.th` | งบการเงินและข้อมูลหุ้น SET |
| `play.google.com`, `itunes.apple.com`, `apps.apple.com` | รีวิวแอป |
| `registry-1.docker.io` (Docker Hub) | ดึง image ตอนติดตั้ง/อัปเดต |
| `acme-v02.api.letsencrypt.org` | ขอใบรับรอง HTTPS (เมื่อตั้ง `SITE_ADDRESS`) |
| webhook ที่ตั้งใน `ALERT_WEBHOOK_URL` | ไม่บังคับ: แจ้งเตือน |

ไม่ต้องเข้า Hugging Face (โมเดลฝังใน image แล้ว)

## ขั้นที่ 1: สร้าง resource ใน Huawei Cloud console

สร้างตามตาราง "Resource บน Huawei Cloud" ด้านบน ตามลำดับ:

1. **VPC + subnet**
2. **Security Group ของ ECS**
3. **ECS** (x86 · 4 vCPU / 8 GiB · Ubuntu 22.04 · ดิสก์ 40 GB SSD · ใส่ Security Group ข้อ 2) + **EIP** แล้วตั้ง **snapshot ของดิสก์**
4. **เฉพาะแบบ RDS:** Security Group ของ RDS แล้วสร้าง **RDS for PostgreSQL** ใน VPC เดียวกับ ECS + ตั้ง backup อัตโนมัติ
5. ไม่บังคับ: Cloud Eye และชี้โดเมนมาที่ EIP

**ต้องตรวจก่อน/ระหว่างสร้าง** (ยังยืนยันจากเอกสารไม่ได้):

- RDS ใน AP-Bangkok เปิด extension `vector` ได้ไหม (ตรวจได้ในขั้นที่ 3) · ไม่ได้ก็ยังใช้ได้ (คิดความใกล้ด้วย numpy แทน) หรือเปลี่ยนไปใช้ container `db`
- endpoint ของอาจารย์รับ request จาก IP ของ Huawei Cloud ไหม (บางที่จำกัด IP) · ลองได้ในขั้นที่ 8

## ขั้นที่ 2: ลง Docker บน ECS

```bash
ssh root@<EIP>              # หรือ user ที่ตั้งไว้
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # แล้ว logout/login ใหม่
docker compose version          # ต้องมี compose plugin
```

## ขั้นที่ 3: ตั้งฐานข้อมูลบน RDS (เฉพาะแบบ RDS)

ใน console ของ RDS (หรือ `psql` จาก ECS) ด้วย user ที่มีสิทธิ์ เช่น root:

```sql
SELECT name FROM pg_available_extensions WHERE name = 'vector';   -- มีแถวคืนมา = ใช้ pgvector ได้
CREATE USER app WITH PASSWORD '<รหัส>';
CREATE DATABASE competitor OWNER app;
\c competitor
CREATE EXTENSION IF NOT EXISTS vector;
```

ไม่มี `vector`: ข้ามบรรทัดสุดท้ายได้ แอปยังใช้งานได้ (log ของ worker จะมีคำเตือน "เปิด pgvector ไม่ได้") · ตารางแอปสร้างให้เองตอนเริ่ม

รหัสผ่าน (ทั้ง RDS และ container `db`) ใช้เฉพาะตัวอักษรและตัวเลข (อักขระพิเศษใน URL ต้อง encode)

## ขั้นที่ 4: ดึงไฟล์ตั้งค่าออกจาก image

```bash
mkdir competitor && cd competitor
docker run --rm quix07/competitor-app:0.5 tar -C /app/deploy -cf - . | tar -xf -
ls -a          # ได้ docker-compose.yml  Caddyfile  Caddyfile.auth  .env.example
cp .env.example .env
chmod 600 .env
nano .env
```

## ขั้นที่ 5: ตั้งค่าใน `.env`

| ตัวแปร | แบบ RDS | แบบ container `db` |
|---|---|---|
| `COMPOSE_PROFILES` | `ocr` | `localdb,ocr` |
| `DATABASE_URL` | `postgresql://app:<รหัส>@<IP ภายในของ RDS>:5432/competitor` | `postgresql://app:<รหัส>@db:5432/competitor` |
| `POSTGRES_PASSWORD` | เว้นว่าง | `<รหัส>` เดียวกับใน `DATABASE_URL` |

ค่าที่เหมือนกันทั้งสองแบบ:

| ตัวแปร | ค่า |
|---|---|
| `LLM_API_KEY` | key ที่ได้มา |
| `OCR_URL` | `http://ocr:8000` |
| `SITE_ADDRESS` | ชื่อโดเมนที่ชี้มาที่ EIP · ไม่มีโดเมนใช้ `<EIP แบบขีด>.sslip.io` เช่น `119-8-1-2.sslip.io` (ได้ HTTPS เหมือนกัน) · เว้นว่าง = HTTP ธรรมดา |
| `MONITOR_AT` | เวลารันชุดติดตามทุกวัน (เวลาไทย) ค่าเริ่ม `07:00` · เว้นว่าง = ไม่รันอัตโนมัติ |
| `BASIC_AUTH_HASH` | เว้นว่างไว้ก่อน ตั้งในขั้นที่ 9 |
| `ALERT_WEBHOOK_URL` | ไม่บังคับ: แจ้งเตือนเข้า Discord / Slack / Teams / Google Chat |
| `HTTP_PORT`, `HTTPS_PORT`, `APP_IMAGE`, `OCR_IMAGE`, `EMBED_*` | เว้นตามค่าเดิม |

`COMPOSE_PROFILES` บอก compose ว่าจะเปิด container ไหนเพิ่ม (`ocr` = container `ocr`, `localdb` = container `db`) · ตั้งครั้งเดียว ทุกคำสั่งหลังจากนี้เป็น `docker compose ...` เฉย ๆ
ไม่ใช้ OCR: ลบ `ocr` ออกจาก `COMPOSE_PROFILES` และเว้น `OCR_URL` ว่าง (PDF ที่มีข้อความในไฟล์ยังอ่านได้ แค่หน้าสแกนอ่านไม่ได้)

## ขั้นที่ 6: เปิดระบบ

```bash
docker compose pull
docker compose up -d
docker compose ps      # web ต้อง (healthy) · แบบ container db: db ต้อง (healthy) · ocr, worker, proxy ต้อง Up
```

## ขั้นที่ 7: ใส่ข้อมูลเดิม (ครั้งเดียว ไม่บังคับ)

ทำก่อนกดวิเคราะห์ครั้งแรก (PostgreSQL ที่มีบริษัทอยู่แล้วจะไม่ย้ายให้ กันข้อมูลซ้ำ) · id เดิมถูกเก็บไว้ · ไฟล์ต้นทางไม่ถูกแก้
copy `app.db` มาไว้ในโฟลเดอร์ `competitor` บน ECS (เช่น `scp app.db root@<EIP>:competitor/`) แล้ว:

```bash
docker compose cp app.db worker:/app/data/import.db
docker compose exec worker python migrate_to_postgres.py /app/data/import.db
```

ต้องจบด้วย "จำนวนแถวตรงกันทุกตาราง"

## ขั้นที่ 8: ทดสอบ

1. เปิด `https://<SITE_ADDRESS>` (หรือ `http://<EIP>` ถ้าไม่ได้ตั้ง)
2. กดชุดตัวอย่างในหน้าภาพรวม 1 ชุด แล้วดูว่าวิเคราะห์จนเสร็จ: `docker compose logs -f worker` (กด Ctrl+C เพื่อออก)
3. ลองถาม 1 คำถามในหน้าถามข้อมูล
4. ลองอัปโหลด PDF 1 ไฟล์ในหน้าข้อมูลภายใน

## ขั้นที่ 9: ตั้งรหัสเข้าเว็บ (ก่อนส่งลิงก์ให้คนนอกทีม)

ค่าเริ่มไม่มีรหัส ใครมีลิงก์ก็เข้าได้ **กดวิเคราะห์ได้ (ใช้ LLM key)** และเห็นข้อมูลภายในที่อัปโหลดไว้ · ทุกคนใช้ user/รหัสชุดเดียวกัน

```bash
docker run --rm caddy:2 caddy hash-password --plaintext 'รหัสผ่านเข้าเว็บ'   # ได้ hash ขึ้นต้น $2a$
nano .env      # BASIC_AUTH_HASH='$2a$14$...'  (ต้องอยู่ใน ' ' เพราะมีตัว $) · BASIC_AUTH_USER=admin (เปลี่ยนได้)
docker compose up -d   # proxy เปลี่ยนไปใช้ Caddyfile.auth ให้เอง
```

ปิดรหัส: ลบค่า `BASIC_AUTH_HASH` ให้ว่างแล้ว `docker compose up -d` · เปลี่ยนรหัส: สร้าง hash ใหม่แล้วทำแบบเดียวกัน

---

## ดูแลระบบ

ทุกคำสั่งรันในโฟลเดอร์ `competitor`

| ต้องการ | คำสั่ง |
|---|---|
| ดูสถานะ | `docker compose ps` |
| ดู log | `docker compose logs -f web` / `worker` / `proxy` / `db` / `ocr` (log ของ docker เก็บไม่เกิน 30 MB ต่อ container) |
| แก้ `.env` แล้วให้มีผล | `docker compose up -d` |
| หยุด / เริ่ม | `docker compose stop` / `docker compose start` |
| ปิดเครื่อง ECS แล้วเปิดใหม่ | container ขึ้นเองอัตโนมัติ (`restart: unless-stopped`) |

**ห้าม** `docker compose down -v` (`-v` ลบ volume = ข้อมูลหายทั้งหมด รวมฐานข้อมูลใน container `db`) ใช้ `docker compose down` เฉย ๆ

### สำรองข้อมูล

**RDS:** backup อัตโนมัติที่ตั้งไว้ในขั้นที่ 1

**container `db`:**

```bash
docker compose exec -T db pg_dump -U app -Fc competitor > backup-$(date +%F).dump                    # สำรอง
docker compose exec -T db pg_restore -U app -d competitor --clean --if-exists < backup-2026-10-12.dump  # คืน
```

**SQLite** (ใช้ backup API ได้ไฟล์ที่สมบูรณ์แม้ระบบกำลังเขียน):

```bash
docker compose exec web python -c "import sqlite3; sqlite3.connect('/app/data/app.db').backup(sqlite3.connect('/app/data/backup.db'))"
docker compose cp web:/app/data/backup.db ./backup-$(date +%F).db
```

ไฟล์ใน volume `app_data` (ข้อมูลดิบ PDF ที่อัปโหลด log) ไม่ได้อยู่ใน DB สำรองด้วย snapshot ของดิสก์ ECS

### อัปเดตเป็นรุ่นใหม่

ข้อมูลใน volume และฐานข้อมูลไม่หาย · `.env` เดิมใช้ต่อได้ (ถ้าเคยตั้ง `APP_IMAGE`/`OCR_IMAGE` ไว้ ให้ลบออกหรือแก้เป็นรุ่นใหม่)
แทน `0.5` ด้วยรุ่นที่ได้รับแจ้ง:

```bash
cd competitor
cp .env .env.backup
docker run --rm quix07/competitor-app:0.5 tar -C /app/deploy -cf - docker-compose.yml Caddyfile Caddyfile.auth .env.example | tar -xf -
docker compose pull
docker compose up -d
```

**มาจาก 0.1 (SQLite):** หลังคำสั่งข้างบน เพิ่ม `DATABASE_URL`, `COMPOSE_PROFILES` (และ `POSTGRES_PASSWORD` ถ้าใช้ container `db`) ตามขั้นที่ 5
แล้ว `docker compose up -d` และย้ายข้อมูล: `docker compose exec worker python migrate_to_postgres.py /app/data/app.db`
(ยังไม่ย้ายก็ได้: เว้น `DATABASE_URL` ว่าง ใช้ SQLite เดิมต่อ)

**SQLite อย่างเดียว ใส่ข้อมูลเดิม:**

```bash
docker compose cp app.db web:/app/data/app.db
docker compose exec -u root web chown app:app /app/data/app.db   # ไม่ทำ = แอปเขียน DB ไม่ได้ (readonly database)
docker compose restart web worker
```

### ต้องการโค้ดไปแก้ต่อ

โค้ดทั้งแอปอยู่ใน image ที่ `/app`: `docker run --rm quix07/competitor-app:0.5 tar -C /app --exclude=./data -cf - . | tar -xf -`

## ปัญหาที่เจอบ่อย

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| `docker compose ps` ไม่เห็น `ocr` หรือ `db` | `COMPOSE_PROFILES` ใน `.env` ไม่ได้ใส่ (ขั้นที่ 5) แล้ว `docker compose up -d` |
| หน้าเว็บ error `failed to resolve host 'db'` | `DATABASE_URL` ชี้ `db` แต่ `COMPOSE_PROFILES` ไม่มี `localdb` |
| `password authentication failed` | รหัสใน `DATABASE_URL` ไม่ตรงกับ `POSTGRES_PASSWORD` · หรือเปลี่ยน `POSTGRES_PASSWORD` หลังสร้าง `db` ครั้งแรก (มีผลแค่ครั้งแรก) แก้ด้วย `docker compose exec db psql -U app -d competitor -c "ALTER USER app PASSWORD '<รหัสใหม่>'"` |
| ต่อ RDS ไม่ได้ (timeout) | ECS กับ RDS ไม่อยู่ VPC เดียวกัน หรือ Security Group ของ RDS ไม่เปิด 5432 ให้ ECS |
| log มี "เปิด pgvector ไม่ได้" | RDS ไม่มี/ไม่ให้สิทธิ์ extension `vector` · แอปใช้ได้ปกติ (คิดความใกล้ด้วย numpy) · เปิดได้ด้วย user root: `CREATE EXTENSION vector;` |
| `exec format error` | ECS เป็น Kunpeng (ARM) ต้องใช้ x86 |
| HTTPS ไม่ขึ้น | โดเมนยังไม่ชี้มา EIP นี้ หรือ Security Group ปิด 80/443 · ดู `docker compose logs proxy` |
| `proxy` ไม่ขึ้น, log บอกเรื่อง basic_auth / hash | ใส่ `BASIC_AUTH_HASH` แล้วไม่ได้ครอบด้วย `'...'` (ตัว `$` ถูกตีความเป็นตัวแปร) |
| ตั้งรหัสแล้วเข้าเว็บได้โดยไม่ถาม | ยังไม่ได้ `docker compose up -d` หลังแก้ `.env` |
| `port is already allocated` · หรือ `proxy` ค้างสถานะ `Created` | มีโปรแกรมอื่นใช้พอร์ต 80 หรือ 443 (บน Windows มักเป็น Docker Desktop/WSL) ดูสาเหตุ: `docker inspect -f '{{.State.Error}}' <ชื่อ container proxy>` · ทดสอบในเครื่อง: ใส่ `HTTP_PORT=8080` / `HTTPS_PORT=8443` (บนเซิร์ฟเวอร์ HTTPS ต้องใช้ 80/443) |
| กดวิเคราะห์แล้วขึ้น "รอคิว" ไม่ขยับ | `worker` ไม่ได้รัน: `docker compose ps` / `docker compose logs worker` |
| วิเคราะห์ error เรื่อง LLM | `LLM_API_KEY` ผิด หรือ endpoint ของอาจารย์ไม่รับ IP ของเซิร์ฟเวอร์ |
| `attempt to write a readonly database` | (SQLite) ลืม `chown` หลัง copy `app.db` |

## ข้อจำกัดตอนนี้

- web/worker รันได้เครื่องเดียว เพราะไฟล์ (ข้อมูลดิบ PDF ที่อัปโหลด log) อยู่ในดิสก์ ECS ถ้าจะแยกหลายเครื่องต้องย้ายไฟล์ไป OBS ก่อน
- รหัสเข้าเว็บเป็นชุดเดียวใช้ร่วมกัน ยังไม่มีระบบ login รายคน
