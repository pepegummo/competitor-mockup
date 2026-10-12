# image แอปหลัก ใช้ทั้ง container web (Streamlit) และ worker (worker.py) ต่างกันแค่คำสั่งที่รัน
FROM python:3.12-slim

# tzdata: ให้ TZ=Asia/Bangkok มีผล (เวลาในฐานข้อมูลและ MONITOR_AT เป็นเวลาไทย)
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Bangkok \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    CC_JOB_QUEUE=1

WORKDIR /app

# torch แบบ CPU ก่อน (ถ้าให้ sentence-transformers ลงเอง จะได้รุ่น CUDA ใหญ่หลาย GB)
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt

# ฝังโมเดล embedding ไว้ใน image: container ไม่ต้องโหลดตอนเริ่ม และใช้ได้แม้ Hugging Face ล่ม
ARG EMBED_MODEL=intfloat/multilingual-e5-small
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBED_MODEL}')"

COPY . .
# ชุดไฟล์สำหรับขึ้นเซิร์ฟเวอร์ (compose, Caddyfile, .env.example, DEPLOY.md) ให้ดึงออกจาก image ได้โดยไม่ต้องมีโค้ด
# compose ชี้ไป image รุ่นเดียวกับที่ build: docker build --build-arg VERSION=0.1 ...
ARG VERSION=latest
RUN sed -i "s/__VERSION__/${VERSION}/g" deploy/docker-compose.yml \
 && cp .env.example DEPLOY.md deploy/
RUN useradd --create-home --uid 1000 app \
 && mkdir -p /app/data \
 && chown -R app:app /app/data /opt/hf
USER app

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4)" || exit 1
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
