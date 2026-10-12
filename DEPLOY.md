# ส่งต่อ: ขึ้นระบบด้วย Docker

คู่มือสำหรับคนที่รับไปขึ้นเซิร์ฟเวอร์ต่อ (ไม่ต้องลง Python ในเครื่อง ใช้แค่ Docker)
ภาพรวมระบบและแผนบน Huawei Cloud อยู่ในโค้ดต้นฉบับ (ขอจากเจ้าของโปรเจกต์) ที่ `docs/architecture.md` และ `docs/huawei-cloud.md`

## มีอะไรบ้าง

| container | ทำอะไร | พอร์ต |
|---|---|---|
| `proxy` | Caddy: HTTPS อัตโนมัติเมื่อตั้งโดเมน · รหัสผ่านก่อนเข้าเว็บ (ถ้าตั้ง `BASIC_AUTH_HASH`) | 80, 443 (ออกนอก) |
| `web` | หน้าเว็บ Streamlit | 8501 (ภายใน) |
| `worker` | รันงานวิเคราะห์ที่กดจากหน้าเว็บ + รันชุดติดตามทุกวันตาม `MONITOR_AT` | – |
| `db` (profile `localdb`) | PostgreSQL + pgvector ในเครื่องนี้ ใช้เมื่อยังไม่มี RDS | 5432 (ภายใน) |
| `ocr` (profile `ocr`) | อ่าน PDF สแกนภาษาไทย (Tesseract) | 8000 (ภายใน) |

`web` กับ `worker` ใช้ image เดียวกัน (`competitor-app`) · ข้อมูลดิบที่ดึงมา PDF ที่อัปโหลด และ log อยู่ใน volume `app_data` เสมอ

### ฐานข้อมูล: เลือก 1 แบบด้วย `DATABASE_URL` ใน `.env`

| แบบ | ตั้งค่า | เหมาะกับ |
|---|---|---|
| **RDS for PostgreSQL** (Huawei) | `DATABASE_URL=postgresql://app:<รหัส>@<IP ภายในของ RDS>:5432/competitor` | ใช้งานจริง: backup อัตโนมัติ ไม่ต้องดูแลเอง |
| **container `db`** | `POSTGRES_PASSWORD=<รหัส>` และ `DATABASE_URL=postgresql://app:<รหัสเดียวกัน>@db:5432/competitor` · รันด้วย `--profile localdb` | ยังไม่มี RDS / ทดสอบ · ต้องสำรองข้อมูลเอง |
| SQLite (แบบเดิม) | เว้น `DATABASE_URL` ว่าง | ข้อมูลน้อย ทดลองเร็ว ๆ |

รหัสผ่านใช้เฉพาะตัวอักษรและตัวเลข (อักขระพิเศษใน URL ต้อง encode)

## สิ่งที่ต้องได้จากเจ้าของโปรเจกต์ (ไม่อยู่ใน image)

- `LLM_API_KEY` (key ของอาจารย์): ขอทางช่องทางส่วนตัว ห้ามใส่ใน git หรือ image (ใส่ใน `.env` บนเซิร์ฟเวอร์เท่านั้น)
- `app.db` ถ้าต้องการข้อมูลที่วิเคราะห์ไว้แล้ว (ไม่มีก็เริ่มจากฐานข้อมูลว่างได้) ย้ายเข้า PostgreSQL ด้วยหัวข้อ "ใส่ข้อมูลเดิม"

## เซิร์ฟเวอร์ที่ต้องใช้

- Linux (เช่น Ubuntu 22.04 บน Huawei ECS) อย่างน้อย 2 vCPU / 4 GB แนะนำ 4 vCPU / 8 GB · ดิสก์ 40 GB
- เปิด Security Group: 80, 443 จากทุกที่ · 22 เฉพาะ IP ทีม
- เครื่องต้องออกเน็ตได้ (เรียก LLM ดึงข่าว)

ลง Docker (Ubuntu):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # แล้ว logout/login ใหม่
```

### ถ้าใช้ RDS for PostgreSQL

1. สร้าง RDS for PostgreSQL ใน **VPC เดียวกับ ECS** (subnet ส่วนตัว ไม่ต้องมี IP สาธารณะ)
2. Security Group ของ RDS: รับพอร์ต 5432 จาก Security Group ของ ECS เท่านั้น
3. ใน console ของ RDS (หรือ `psql` จาก ECS) สร้าง database และ user ของแอป:
   ```sql
   CREATE USER app WITH PASSWORD '<รหัส>';
   CREATE DATABASE competitor OWNER app;
   \c competitor
   CREATE EXTENSION IF NOT EXISTS vector;   -- ค้นด้วยความหมาย (pgvector) ต้องใช้ user ที่มีสิทธิ์ เช่น root
   ```
   ถ้า RDS ไม่มี extension `vector` (ตรวจ: `SELECT name FROM pg_available_extensions WHERE name = 'vector';`) แอปยังใช้งานได้
   แค่คิดความใกล้ด้วย numpy แทน (log ของ worker จะมีคำเตือน "เปิด pgvector ไม่ได้")
4. ใส่ `DATABASE_URL` ที่ชี้ IP ภายในของ RDS ใน `.env` (ด้านล่าง) · แอปสร้างตารางให้เองตอนเริ่ม

## ขึ้นระบบ

ไม่ต้อง clone โค้ด ไฟล์ที่ต้องใช้ทั้งหมด (`docker-compose.yml`, `Caddyfile`, `.env.example`, คู่มือนี้) ฝังอยู่ใน image ดึงออกมาได้เลย:

```bash
mkdir competitor && cd competitor
docker run --rm quix07/competitor-app:0.2 tar -C /app/deploy -cf - . | tar -xf -
ls -a          # ได้ docker-compose.yml  Caddyfile  Caddyfile.auth  .env.example  DEPLOY.md
cp .env.example .env
nano .env
```

ค่าที่ต้องใส่ใน `.env`:

| ตัวแปร | ค่า |
|---|---|
| `LLM_API_KEY` | key ที่ได้มา |
| `DATABASE_URL` | ตามแบบฐานข้อมูลที่เลือก (ตารางด้านบน) |
| `POSTGRES_PASSWORD` | เฉพาะแบบ container `db` · ต้องตรงกับรหัสใน `DATABASE_URL` |
| `BASIC_AUTH_HASH` | ไม่บังคับ · เว้นว่าง = ไม่มีรหัส ทุกคนที่มีลิงก์เข้าได้ · ตั้งรหัส: ดูหัวข้อ "เปิดรหัสผ่านเข้าเว็บ" |
| `SITE_ADDRESS` | ชื่อโดเมนที่ชี้มาที่เครื่อง ไม่มีโดเมนใช้ `<EIP แบบขีด>.sslip.io` เช่น `119-8-1-2.sslip.io` · เว้นว่าง = HTTP ธรรมดา |
| `MONITOR_AT` | เวลารันชุดติดตามทุกวัน (เวลาไทย) เช่น `07:00` · เว้นว่าง = ไม่รันอัตโนมัติ |
| `OCR_URL` | `http://ocr:8000` ถ้าเปิด OCR · เว้นว่างถ้าไม่ใช้ |

`APP_IMAGE` / `OCR_IMAGE` เว้นว่างได้ (compose ชี้ไป `quix07/competitor-app:0.2` และ `quix07/competitor-ocr:0.2` อยู่แล้ว)

```bash
docker compose up -d                                  # ใช้ RDS (หรือ SQLite)
docker compose --profile localdb up -d                # ใช้ container db
docker compose --profile localdb --profile ocr up -d  # container db + OCR
docker compose ps                                     # web ต้องขึ้น (healthy) · db ต้อง healthy
```

ทุกคำสั่ง `docker compose` หลังจากนี้ใส่ `--profile` ชุดเดิมด้วย (ไม่ใส่ = container ใน profile นั้นไม่ถูกสั่ง)

image เป็น `linux/amd64` ใช้กับ ECS แบบ x86 · ECS แบบ Kunpeng (ARM) ใช้ไม่ได้ ต้องขอโค้ดไป build เอง

เปิด `https://<SITE_ADDRESS>` (หรือ `http://<IP>` ถ้าไม่ได้ตั้ง) (ใส่ user/รหัสถ้าตั้งไว้) → กดชุดตัวอย่างในหน้าภาพรวม 1 ชุด
ดูว่าวิเคราะห์จนเสร็จ (`docker compose logs -f worker`) และลองถาม 1 คำถามในหน้าถามข้อมูล

### เปิดรหัสผ่านเข้าเว็บ (ไม่บังคับ)

ค่าเริ่มไม่มีรหัส ใครมีลิงก์ก็เข้าได้ และ**กดวิเคราะห์ได้ (ใช้ LLM key)** และเห็นข้อมูลภายในที่อัปโหลดไว้
เมื่อจะเปิดให้คนนอกทีมเห็นลิงก์ ควรตั้งรหัส (ทุกคนใช้ user/รหัสชุดเดียวกัน):

```bash
docker run --rm caddy:2 caddy hash-password --plaintext 'รหัสผ่านเข้าเว็บ'   # ได้ hash ขึ้นต้น $2a$
nano .env      # BASIC_AUTH_HASH='$2a$14$...'  (ต้องอยู่ใน ' ' เพราะมีตัว $) · BASIC_AUTH_USER=admin (เปลี่ยนได้)
docker compose up -d   # (ใส่ --profile ชุดเดิม) proxy เปลี่ยนไปใช้ Caddyfile.auth ให้เอง
```

ปิดรหัสอีกครั้ง: ลบค่า `BASIC_AUTH_HASH` ให้ว่างแล้ว `docker compose up -d` · เปลี่ยนรหัส: สร้าง hash ใหม่แล้วทำแบบเดียวกัน

ต้องการโค้ดไปแก้ต่อ: โค้ดทั้งแอปอยู่ใน image ที่ `/app` ดึงออกมาได้ด้วย
`docker run --rm quix07/competitor-app:0.2 tar -C /app --exclude=./data -cf - . | tar -xf -`

### ใส่ข้อมูลเดิม (ครั้งเดียว)

**PostgreSQL (RDS หรือ container `db`):** ย้ายจากไฟล์ SQLite ด้วยสคริปต์ในแอป ทำก่อนกดวิเคราะห์ครั้งแรก
(PostgreSQL ที่มีบริษัทอยู่แล้วจะไม่ย้ายให้ กันข้อมูลซ้ำ) · id เดิมถูกเก็บไว้ ผลที่เปิดค้างไว้ยังเปิดได้

```bash
docker compose cp app.db worker:/app/data/import.db
docker compose exec worker python migrate_to_postgres.py /app/data/import.db
```

สคริปต์แสดงจำนวนแถวต่อตาราง SQLite เทียบกับ PostgreSQL · ไฟล์ต้นทางไม่ถูกแก้

**SQLite:** วาง `app.db` ไว้ในโฟลเดอร์โปรเจกต์ แล้ว:

```bash
docker compose cp app.db web:/app/data/app.db
docker compose exec -u root web chown app:app /app/data/app.db   # ไม่ทำ = แอปเขียน DB ไม่ได้ (readonly database)
docker compose restart web worker
```

### อัปเกรดจาก 0.1 (SQLite) เป็น 0.2 (PostgreSQL)

ข้อมูลเดิมอยู่ใน `/app/data/app.db` ของ volume `app_data` ไม่หายระหว่างอัปเกรด

```bash
cd competitor
cp .env .env.backup
docker run --rm quix07/competitor-app:0.2 tar -C /app/deploy -cf - docker-compose.yml Caddyfile Caddyfile.auth .env.example DEPLOY.md | tar -xf -
nano .env      # ลบ APP_IMAGE/OCR_IMAGE ที่เป็น 0.1 ออก (หรือแก้เป็น 0.2) · เพิ่ม DATABASE_URL (และ POSTGRES_PASSWORD ถ้าใช้ container db)
docker compose --profile localdb pull
docker compose --profile localdb up -d
docker compose exec worker python migrate_to_postgres.py /app/data/app.db
```

(ใช้ RDS: ตัด `--profile localdb` ออก) · ยังไม่ย้ายก็ได้: เว้น `DATABASE_URL` ว่าง 0.2 ใช้ SQLite เดิมต่อได้

## ดูแลระบบ

| ต้องการ | คำสั่ง |
|---|---|
| ดู log | `docker compose logs -f web` / `worker` / `proxy` / `db` (log ของ docker เก็บไม่เกิน 30 MB ต่อ container) |
| อัปเดตเวอร์ชันใหม่ (เช่น 0.3) | ใส่ `APP_IMAGE=quix07/competitor-app:0.3` และ `OCR_IMAGE=quix07/competitor-ocr:0.3` ใน `.env` แล้ว `docker compose pull && docker compose up -d` (ข้อมูลไม่หาย) |
| แก้ `.env` แล้วให้มีผล | `docker compose up -d` |
| หยุด / เริ่ม | `docker compose stop` / `docker compose start` |
| สำรองข้อมูล | ดูด้านล่าง |

### สำรองข้อมูล

**RDS:** ตั้ง backup อัตโนมัติใน console ของ RDS (เช่น เก็บ 7 วัน) ไม่ต้องทำเอง

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

ไฟล์ใน volume `app_data` (ข้อมูลดิบ PDF ที่อัปโหลด log) ไม่ได้อยู่ใน DB สำรองด้วย snapshot ของดิสก์ ECS (EVS)

**ห้าม** `docker compose down -v` (`-v` ลบ volume = ข้อมูลหายทั้งหมด รวมฐานข้อมูลใน container `db`) ใช้ `docker compose down` เฉย ๆ

## ปัญหาที่เจอบ่อย

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| `proxy` ไม่ขึ้น, log บอกเรื่อง basic_auth / hash | ใส่ `BASIC_AUTH_HASH` แล้วไม่ได้ครอบด้วย `'...'` (ตัว `$` ถูกตีความเป็นตัวแปร) |
| ตั้งรหัสแล้วเข้าเว็บได้โดยไม่ถาม | ยังไม่ได้ `docker compose up -d` หลังแก้ `.env` (proxy ต้องสร้างใหม่ถึงจะเปลี่ยนไฟล์ Caddyfile) |
| `port is already allocated` · หรือเปิดเว็บไม่ได้และ `docker compose ps -a` เห็น `proxy` ค้างสถานะ `Created` | มีโปรแกรมอื่นใช้พอร์ต 80 หรือ 443 (บน Windows มักเป็น Docker Desktop/WSL จอง 443) ดูสาเหตุ: `docker inspect -f '{{.State.Error}}' <ชื่อ container proxy>` · แก้: ใส่ `HTTP_PORT=8080` / `HTTPS_PORT=8443` ใน `.env` แล้ว `docker compose up -d` (ใช้ตอนทดสอบในเครื่องเท่านั้น บนเซิร์ฟเวอร์ HTTPS ต้องใช้ 80/443) |
| HTTPS ไม่ขึ้น | โดเมนยังไม่ชี้มา IP นี้ หรือ Security Group ปิด 80/443 · ดู `docker compose logs proxy` |
| กดวิเคราะห์แล้วขึ้น "รอคิว" ไม่ขยับ | `worker` ไม่ได้รัน: `docker compose ps` / `docker compose logs worker` |
| หน้าเว็บ error `failed to resolve host 'db'` | `DATABASE_URL` ชี้ `db` แต่ไม่ได้รันด้วย `--profile localdb` |
| `password authentication failed` | รหัสใน `DATABASE_URL` ไม่ตรงกับ `POSTGRES_PASSWORD` · หรือเปลี่ยน `POSTGRES_PASSWORD` หลังสร้าง `db` ครั้งแรก (มีผลแค่ครั้งแรก) แก้ด้วย `docker compose exec db psql -U app -d competitor -c "ALTER USER app PASSWORD '<รหัสใหม่>'"` |
| ต่อ RDS ไม่ได้ (timeout) | ECS กับ RDS ไม่อยู่ VPC เดียวกัน หรือ Security Group ของ RDS ไม่เปิด 5432 ให้ ECS |
| log มี "เปิด pgvector ไม่ได้" | RDS ไม่มี/ไม่ให้สิทธิ์ extension `vector` · แอปใช้ได้ปกติ (คิดความใกล้ด้วย numpy) · เปิดได้ด้วย user root: `CREATE EXTENSION vector;` |
| `attempt to write a readonly database` | (SQLite) ลืม `chown` หลัง copy `app.db` |
| วิเคราะห์ error เรื่อง LLM | `LLM_API_KEY` ผิด หรือ endpoint ของอาจารย์ไม่รับ IP ของเซิร์ฟเวอร์ |

## ยังไม่ได้ทำ

ไฟล์ (ข้อมูลดิบ PDF ที่อัปโหลด log) ยังอยู่ในดิสก์ของ ECS ไม่ได้ย้ายไป OBS · ใช้ web/worker ได้เครื่องเดียว
(ถ้าจะแยกหลายเครื่องต้องย้ายไฟล์ไป OBS ก่อน แผนอยู่ใน `docs/huawei-cloud.md` ของโค้ด)
