# --- stage 1: build the SPA -------------------------------------------------
FROM node:22-alpine AS web

WORKDIR /build
COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY web/ ./
RUN npm run build

# --- stage 2: runtime -------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl is here for the compose healthcheck, nothing else.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir \
      "fastapi>=0.115" "uvicorn[standard]>=0.32" "sqlalchemy[asyncio]>=2.0.36" \
      "asyncpg>=0.30" "alembic>=1.14" "pydantic>=2.10" "pydantic-settings>=2.7" \
      "python-multipart>=0.0.20" "anthropic>=0.69" "pillow>=11.0" \
      "itsdangerous>=2.2" "argon2-cffi>=23.1"

COPY alembic.ini ./
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY --from=web /build/dist ./web/dist

# TrueNAS SCALE runs apps as uid/gid 568 (the `apps` user). Matching it here means
# bind-mounted receipt images and the database directory get sane ownership.
RUN useradd --uid 568 --user-group --no-create-home --shell /usr/sbin/nologin apps \
 && mkdir -p /data \
 && chown -R 568:568 /data /app
USER 568:568

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
