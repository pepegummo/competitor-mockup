"""service อ่าน PDF (รันเป็น container ocr): POST /extract รับไฟล์ คืนข้อความทีละหน้า"""
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from extract import extract_pages

app = FastAPI(title="competitor-ocr")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/extract")
async def extract(file: UploadFile = File(...), first: int = Form(1), last: int | None = Form(None)):
    data = await file.read()
    try:
        pages = await run_in_threadpool(extract_pages, data, True, first, last)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"pages": pages}
