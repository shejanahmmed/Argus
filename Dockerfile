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
    ARGUS_ENV=development \
    ARGUS_ALLOW_ANONYMOUS=true \
    ARGUS_STORAGE_BACKEND=sqlite \
    ARGUS_DB_PATH=/app/.argus_logs/argus.db \
    HOME=/home/argus

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged system user (UID 1000 for Kubernetes, Linux, and Hugging Face Spaces compatibility)
RUN useradd -m -u 1000 -s /bin/bash argus && \
    mkdir -p /app/.argus_logs && \
    chown -R argus:argus /app /home/argus

COPY LICENSE pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

COPY --from=frontend-builder --chown=argus:argus /app/dashboard/dist ./dashboard/dist

RUN chown -R argus:argus /app

USER 1000:1000

EXPOSE 8000 7860

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=5s \
    CMD curl -f http://localhost:${PORT:-8000}/healthz || exit 1

ENTRYPOINT ["python", "-m", "argus"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
