# ไดอะแกรมแบบโต้ตอบ

ไดอะแกรมของระบบที่สร้างด้วย [archify](https://skills.sh/tt-a1i/archify) แต่ละอันเป็นไฟล์ HTML ไฟล์เดียว (ฟอนต์และ viewer ฝังในไฟล์ เปิดได้โดยไม่ต้องมีเน็ต)
ซูม กดดูรายละเอียดแต่ละกล่อง สลับธีมสว่าง/มืด และ Export เป็น PNG / SVG ได้ ป้ายทั้งหมดเป็นภาษาอังกฤษ

**วิธีเปิด:** ดับเบิลคลิกไฟล์ `.html` ในเครื่อง · GitHub แสดงไฟล์ HTML เป็นโค้ด ไม่ render
กล่องที่มีป้าย `SRC` ลิงก์ไปบรรทัดในโค้ดที่ commit `37cee1c` บน GitHub (เปิดได้หลัง push)

ป้ายในภาพอัปเดตเป็น PostgreSQL + pgvector, worker ตาม `MONITOR_AT` และรหัสผ่านไม่บังคับแล้ว
(กล่อง "Daily trigger" ในภาพ monitor ไม่มีลิงก์ `SRC` เพราะ `worker.py` ยังไม่มีใน commit `37cee1c` ที่ลิงก์ชี้อยู่)
ภาพไฟล์ไหนเรียกไฟล์ไหนของทั้งระบบ ดู [`system-flow.md`](../system-flow.md) และ `system-flow-*.png` / `.svg` ในโฟลเดอร์นี้

| ไดอะแกรม | ชนิด | ระบบ | เอกสาร |
|---|---|---|---|
| [Analysis pipeline](analysis-pipeline.html) | dataflow | ภาพรวม: แหล่งข้อมูล → จัดหมวด → ตาราง → รายงาน | [architecture.md](../architecture.md) |
| [Ask (RAG) sequence](ask-rag.html) | sequence | ถามข้อมูล: parse → similarity → ตัวเลข → คำตอบ | [ask.md](../systems/ask.md) |
| [Huawei Cloud plan](huawei-cloud.html) | architecture | แผน deploy (ยังไม่ได้สร้าง) | [huawei-cloud.md](../huawei-cloud.md) |
| [Data collection](collect.html) | dataflow | ดึงข้อมูลและกันซ้ำ | [collect.md](../systems/collect.md) |
| [Classification loop](classify.html) | workflow | จัดหมวดด้วย LLM + วนกลับจากการตรวจความแม่น | [classify.md](../systems/classify.md) |
| [Background job](background-job.html) | sequence | ปุ่มเริ่มวิเคราะห์ → `monitor.py --job` (บนเครื่อง) หรือ `worker.py` (docker) → เปิดผลเอง | [analysis-report.md](../systems/analysis-report.md) |
| [Monitoring](monitor.html) | workflow | ติดตามอัตโนมัติและแจ้งเตือน | [monitor.md](../systems/monitor.md) |
| [Market data](market.html) | dataflow | งบ SET · อันดับในหมวด · ราคาหุ้นหลังข่าว | [market.md](../systems/market.md) |
| [Find competitors](discover.html) | workflow | หาคู่แข่ง Phase 3 | [discover-groups.md](../systems/discover-groups.md) |
| [Corporate groups](corporate-groups.html) | workflow | บริษัทในเครือ + ตรวจผู้ถือหุ้น | [discover-groups.md](../systems/discover-groups.md) |
| [PDF upload + OCR](pdf-ocr.html) | dataflow | อ่าน PDF และ OCR | [internal-docs.md](../systems/internal-docs.md) |
| [LLM call lifecycle](llm-call.html) | lifecycle | ลองใหม่ บันทึก เล่นซ้ำ fallback | [platform.md](../systems/platform.md) |

## แก้และสร้างใหม่

ต้นทางคือไฟล์ `<ชื่อ>.json` ข้าง HTML แก้แล้วรัน (ต้องติดตั้ง skill archify และมี Chrome หรือ Edge):

```powershell
$env:ARCHIFY_CHROME = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"   # ถ้าไม่มี Chrome
node "$env:USERPROFILE\.claude\skills\archify\bin\archify.mjs" finalize <ชนิด> docs/diagrams/<ชื่อ>.json docs/diagrams/<ชื่อ>.html --repo-root . --quality showcase --json
```

`<ชนิด>` = `dataflow` · `sequence` · `architecture` · `workflow` · `lifecycle` ตามตารางด้านบน (ไดอะแกรม Huawei ไม่ต้องใส่ `--repo-root` เพราะไม่ได้อ้างโค้ด)
ถ้าแก้โค้ดจนเลขบรรทัดเปลี่ยน ให้แก้ `meta.repository.revision` เป็น commit ใหม่และแก้ `sources` ให้ตรง ไม่งั้นขั้นตรวจหลักฐานจะไม่ผ่าน
ไฟล์ผลการรัน (`*.finalize*.json`, `*.delivery.json`, `*.browser-check.json`) ถูก ignore เพราะมี path ในเครื่อง
