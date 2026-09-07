# --- stage 1: build the SPA -------------------------------------------------
FROM node:22-alpine AS web

WORKDIR /build
COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY web/ ./
RUN npm run build

# --- stage 2: runtime -------------------------------------------------------
FROM python:3.12-slim

# Stamped by CI so the running app can say which build it is. Without this, answering
# "did the update take?" means opening a shell on the NAS to compare image digests.
ARG BUILD_COMMIT=""
ARG BUILD_TIME=""
ARG BUILD_IMAGE=""

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    BUILD_COMMIT=$BUILD_COMMIT \
    BUILD_TIME=$BUILD_TIME \
    BUILD_IMAGE=$BUILD_IMAGE

# Standard OCI labels. These are what makes GHCR link the package back to this repository,
# and what `docker inspect` reports - so "which build is this and where did it come from"
# has an answer from outside the app as well as from the Rendszer page inside it.
LABEL org.opencontainers.image.title="Receipt Tracker" \
      org.opencontainers.image.description="Photograph a receipt, get a queryable expense database." \
      org.opencontainers.image.source="https://github.com/Cloudhunter77/mazsola_enterprise" \
      org.opencontainers.image.url="https://github.com/Cloudhunter77/mazsola_enterprise" \
      org.opencontainers.image.documentation="https://github.com/Cloudhunter77/mazsola_enterprise/blob/main/deploy/README.md" \
      org.opencontainers.image.licenses="NOASSERTION" \
      org.opencontainers.image.revision=$BUILD_COMMIT \
      org.opencontainers.image.created=$BUILD_TIME \
      org.opencontainers.image.version=$BUILD_COMMIT

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
