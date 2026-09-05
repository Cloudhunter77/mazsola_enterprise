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

# Dependencies come from pyproject.toml, never a list repeated here. A hardcoded copy
# drifted once already: httpx was added for the OpenRouter engine and not mirrored here,
# so the published image could not import app.extraction.factory - which every engine
# goes through - and the container would not start at all.
COPY pyproject.toml ./
RUN python -c "\
import tomllib; \
print('\\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))\
" > /tmp/requirements.txt \
 && cat /tmp/requirements.txt \
 && pip install --no-cache-dir -r /tmp/requirements.txt

COPY alembic.ini ./
COPY app/ ./app/
COPY scripts/ ./scripts/
# The test fixtures ship too: scripts/try_extract.py - the documented pre-install smoke
# test - reads tests/fixtures/receipts/synthetic_tesco.jpg, and a fixture that exists in
# the repository but not in the image made that command fail for the person following
# the deploy guide.
COPY tests/ ./tests/
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
