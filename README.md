# Mazsola

Photograph a receipt, get a queryable expense database. Self-hosted, built for
TrueNAS SCALE and for Hungarian receipts.

You take a photo. The app reads the shop, the date, every line item, the ÁFA rates and
the total, checks that the arithmetic actually balances, and stores it. From there it can
answer the questions that save money: what a given product costs over time, which shop is
cheapest for the basket you actually buy, and what your own personal inflation looks like.

## How it works

```
phone camera / iOS Shortcut
        │  POST /api/receipts
        ▼
   app container ──────────────► extraction engine (Claude by default)
   FastAPI + SPA + worker              │
        │                              ▼
        ▼                     validated against the arithmetic
   PostgreSQL                  a real Hungarian receipt must satisfy
```

Two containers, no queue service. Upload state lives in the database, so a restart
resumes rather than loses work.

## What it does about Hungarian receipts specifically

Most receipt-parsing errors are not OCR errors - the characters read fine - they are
misclassification. So the app knows that:

- **`VISSZAJÁRÓ` is not a purchase.** Nor is `KÉSZPÉNZ`, `ÖSSZESEN`, or
  `Ön ma megtakarított`. Counting change as spending is the single most common way these
  systems silently inflate your totals.
- **`BETÉTDÍJ` is money you paid, but it is not groceries**, and `KEDVEZMÉNY` reduces the
  total rather than adding to it.
- **`KEREKÍTÉS` is cash rounding**, always between -2 and +2 Ft, and a cash total is always
  a multiple of 5.
- A two-line item (`COCA COLA 1,75L` then `2 db x 549`) is **one** purchase, not two.
- ÁFA collector letters (A=27%, B=18%, C=5%, AM=mentes) are read from the legend printed
  on the receipt.
- `1 234,56` is one thousand two hundred thirty-four, and `2026.08.14.` is a date.

Every extraction is then checked:
`sum(items) − discounts + rounding == total`, plus the ÁFA block's own arithmetic. A
receipt that does not balance goes to a review queue instead of into your statistics.

## Getting started

**On the NAS:** see [`deploy/README.md`](deploy/README.md).

**Locally:**

```bash
cp .env.example .env          # add your ANTHROPIC_API_KEY
docker compose -f docker-compose.dev.yaml up --build
open http://localhost:8000
```

**Without Docker:**

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
cd web && npm install && npm run build && cd ..
export DATABASE_URL=postgresql+asyncpg://mazsola:mazsola@localhost:5432/mazsola
export ANTHROPIC_API_KEY=sk-ant-...
export AUTH_DISABLED=true     # local only
.venv/bin/uvicorn app.main:app --reload
```

Migrations and the Hungarian category tree are applied at startup; there is no separate
setup step.

Want to see the dashboard before you have any receipts?

```bash
python scripts/seed_demo.py --yes     # plausible fake shopping data
python scripts/seed_demo.py --clear   # removes exactly what it created
```

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://mazsola:mazsola@db:5432/mazsola` | |
| `DATA_DIR` | `/data` | Where receipt photos are stored |
| `EXTRACTOR` | `claude` | `claude`, `tesseract` or `ollama` |
| `EXTRACTOR_MODEL` | `claude-opus-5` | `claude-haiku-4-5` costs about a fifth as much |
| `EXTRACTOR_EFFORT` | `medium` | Transcription does not repay deep reasoning |
| `ANTHROPIC_API_KEY` | – | Required when `EXTRACTOR=claude`; a Console key, not a Pro/Max subscription |
| `MAX_IMAGE_EDGE` | `1600` | The main cost lever; images bill at `w×h/750` tokens |
| `SECRET_KEY` | – | Signs the session cookie |
| `APP_PASSWORD_HASH` | – | `python scripts/hash_password.py` |
| `API_KEY` | – | For the iOS Shortcut's `X-API-Key` header |
| `AUTH_DISABLED` | `false` | Local development only |
| `WORKER_ENABLED` | `true` | Off means uploads queue but are not read |

## What it costs to run

Extraction is the only running cost. At a downscaled ~3k input tokens and ~1.2k output
tokens per receipt:

| Model | Per receipt | ~20 receipts/week |
|---|---|---|
| `claude-opus-5` | ~$0.045 | ~$47/year |
| `claude-sonnet-5` | ~$0.018 | ~$19/year |
| `claude-haiku-4-5` | ~$0.009 | ~$9/year |

The app records the real token cost of every extraction and shows it under
**Felismerési költség**, so the choice can be made on your own numbers rather than on
these estimates. Switching is one environment variable.

## Moving off the API later

`app/extraction/base.py` defines the whole contract: image bytes in, an `ExtractedReceipt`
out. `claude.py` is one implementation; `local.py` holds working stubs for a Tesseract or
Ollama engine with the intended shape sketched out. Nothing else in the app knows which
engine ran, so swapping is a new file plus `EXTRACTOR=...`.

## Tests

```bash
pytest -q                # needs TEST_DATABASE_URL pointing at a PostgreSQL
pytest -m live -s        # hits the real API, costs a few cents, needs ANTHROPIC_API_KEY
```

The default suite covers the Hungarian rules, ingest deduplication, worker retry and
failure handling, and the statistics queries, with the extraction engine stubbed. The live
suite is the one that measures whether reading is actually accurate - drop photos of your
own receipts into `tests/fixtures/receipts/` and they are picked up automatically.

## Licence

Personal project; do as you like with it.
