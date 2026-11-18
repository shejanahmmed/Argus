# Multi-stage production Dockerfile for Argus AgentOps & C2 Control Plane

# --- Stage 1: Build Frontend Dashboard ---
FROM node:22-alpine AS frontend-builder
WORKDIR /app/dashboard

COPY dashboard/package*.json ./
RUN npm ci

COPY dashboard/ ./
RUN npm run build

# --- Stage 2: Production Python Runtime ---
FROM python:3.11-slim AS runner
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ARGUS_ENV=production \
    ARGUS_STORAGE_BACKEND=sqlite \
    ARGUS_DB_PATH=/app/.argus_logs/argus.db

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml aboutArgus.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

COPY --from=frontend-builder /app/dashboard/dist ./dashboard/dist

RUN mkdir -p /app/.argus_logs

EXPOSE 8000 7860

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=5s \
    CMD curl -f http://localhost:${PORT:-8000}/healthz || exit 1

ENTRYPOINT ["python", "-m", "argus"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
