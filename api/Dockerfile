# Build from the repo root, e.g.:
#   docker build -f api/Dockerfile -t <image> .
# (not from this directory - it needs shared/ and web/ as build context too.)

# Stage 1: build the React app into web/dist.
FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
# --ignore-scripts: no package install scripts run (none are needed to build).
RUN npm ci --ignore-scripts
COPY web/ ./
RUN npm run build

# Stage 2: the API, which also serves the built app (api/app/main.py).
FROM python:3.12-slim

WORKDIR /app

COPY shared/ ./shared/
COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

COPY api/app/ ./api/app/
COPY --from=web /web/dist ./web/dist

ENV PYTHONPATH=/app
EXPOSE 8080

CMD exec uvicorn api.app.main:app --host 0.0.0.0 --port ${PORT:-8080}
