# syntax=docker/dockerfile:1
# Single-origin image: Vite build → backend/static, FastAPI on Cloud Run PORT (default 8080).

FROM node:20-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Same-origin API calls (empty base → fetch("/api/...")).
ENV VITE_API_BASE_URL=
RUN npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PORT=8080

COPY backend/requirements.txt /app/backend/
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/ /app/backend/
COPY --from=frontend /frontend/dist /app/backend/static/

RUN chmod +x /app/backend/docker-entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/app/backend/docker-entrypoint.sh"]
