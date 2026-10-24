FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd -m app && mkdir -p /data && chown -R app /app /data
USER app
ENV KNOWLEDGE_STORE_PATH=/data/knowledge_store.json

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8000')+'/health')"

# One worker on purpose: sessions, metrics and workflow runs live in process
# memory. Scale by adding threads (default) or moving that state to Redis.
CMD ["sh", "-c", "uvicorn api.app:app_factory --factory --host 0.0.0.0 --port ${PORT}"]
