# Build from the repo root, e.g.:
#   docker build -f api/Dockerfile -t <image> .
# (not from this directory - it needs shared/ as build context too.)
FROM python:3.12-slim

WORKDIR /app

COPY shared/ ./shared/
COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

COPY api/app/ ./api/app/

ENV PYTHONPATH=/app
EXPOSE 8080

CMD exec uvicorn api.app.main:app --host 0.0.0.0 --port ${PORT:-8080}
