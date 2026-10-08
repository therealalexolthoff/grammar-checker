# Build from the repo root, e.g.:
#   docker build -f harness/Dockerfile -t <image> .
# (not from this directory - it needs shared/ as build context too.)
FROM python:3.12-slim

WORKDIR /app

COPY shared/ ./shared/
COPY harness/requirements.txt ./harness/requirements.txt
RUN pip install --no-cache-dir -r harness/requirements.txt

COPY harness/app/ ./harness/app/

ENV PYTHONPATH=/app
EXPOSE 8080

CMD exec uvicorn harness.app.main:app --host 0.0.0.0 --port ${PORT:-8080}
