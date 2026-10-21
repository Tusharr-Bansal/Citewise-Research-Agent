# Citewise web app. Postgres lives outside the container (Neon); see docs/decisions/0015.
FROM python:3.12-slim

# poppler-utils: pdftotext, which reads every uploaded PDF (decision 0007).
# postgresql-client: psql, used once on first start to load the demo project into an empty database.
RUN apt-get update \
 && apt-get install -y --no-install-recommends poppler-utils postgresql-client \
 && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 app
USER app
WORKDIR /home/app/citewise
ENV PATH=/home/app/.local/bin:$PATH PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1

COPY --chown=app requirements.txt .
RUN pip install --user -r requirements.txt

# Embedding model, baked into the image so cold starts don't download it.
RUN python -c "from huggingface_hub import snapshot_download; \
snapshot_download('Qdrant/bge-small-en-v1.5-onnx-Q', local_dir='models/bge-small-en-v1.5-onnx-Q', \
allow_patterns=['*.json','*.onnx','vocab.txt'])"

COPY --chown=app src ./src
COPY --chown=app deploy/demo_data.sql.gz ./deploy/

ENV PYTHONPATH=/home/app/citewise/src \
    CITEWISE_EMBED_MODEL_PATH=/home/app/citewise/models/bge-small-en-v1.5-onnx-Q \
    CITEWISE_EMBED_THREADS=1
# Render sets $PORT. One worker: the app holds in-memory indexes and rate limits.
CMD ["sh", "-c", "exec uvicorn citewise.app:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips='*'"]
