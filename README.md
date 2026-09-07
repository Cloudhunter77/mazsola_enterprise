# Receipt Tracker

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
- A receipt too long to photograph legibly in one frame is captured in overlapping
  sections and read as **one** document — a line visible in two sections is counted once.
- ÁFA collector letters (A=27%, B=18%, C=5%, AM=mentes) are read from the legend printed
  on the receipt.
- `1 234,56` is one thousand two hundred thirty-four, and `2026.08.14.` is a date. The
  thousands separator is a **space**, and dropping the group before it — reading `8 999` as
  `999` — is the one misreading that can be wrong by an order of magnitude while still
  looking plausible, so the prompt drills it and the total is cross-checked against the
  model's own transcription of the printed figure.

Every extraction is then checked:
`sum(items) − discounts + rounding == total`, plus the ÁFA block's own arithmetic. A
receipt that does not balance goes to a review queue instead of into your statistics.

## Spending that never printed a receipt

Not everything you spend produces a photograph, and anything left out quietly makes the
statistics wrong.

- **Kézi rögzítés** — type in a receipt you lost. Shop, date, lines; the total defaults to
  the sum, so "Lidl, 4 200 Ft" as a single line is a valid entry. It is stored `confirmed`
  rather than queued for review: you entered the numbers, so there is nothing to check.
- **Előfizetések** — Spotify, YouTube, the gym. Set the amount and the day once and each
  month's charge appears by itself, as an ordinary receipt. A start date in the past
  backfills. Pausing stops future charges and keeps everything already recorded, because a
  cancelled subscription is still part of last year's spending.

Both become ordinary `receipts` rows, so every statistic counts them without knowing they
were never photographed.

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
export DATABASE_URL=postgresql+asyncpg://receipts:receipts@localhost:5432/receipts
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
| `DATABASE_URL` | `postgresql+asyncpg://receipts:receipts@db:5432/receipts` | |
| `DATA_DIR` | `/data` | Where receipt photos are stored |
| `EXTRACTOR` | `claude` | `openrouter`, `claude`, `tesseract` or `ollama` |
| `OPENROUTER_API_KEY` | – | Required when `EXTRACTOR=openrouter` |
| `OPENROUTER_MODEL` | `anthropic/claude-sonnet-4.5` | Must support vision **and** structured outputs |
| `EXTRACTOR_MODEL` | `claude-opus-5` | `claude-haiku-4-5` costs about a fifth as much |
| `EXTRACTOR_EFFORT` | `medium` | Transcription does not repay deep reasoning |
| `ANTHROPIC_API_KEY` | – | Required when `EXTRACTOR=claude`; a Console key, not a Pro/Max subscription |
| `MAX_IMAGE_EDGE` | `1600` | The main cost lever; images bill at `w×h/750` tokens |
| `MIN_IMAGE_WIDTH` | `800` | Floor on width, overriding the edge cap on tall receipts |
| `BUILD_COMMIT` | – | Stamped by CI; shown on the Rendszer page so an update can be verified |
| `MAX_PARTS` | `8` (in code) | Most photos one receipt may be captured in |
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

## Choosing an extraction engine

`EXTRACTOR` picks one. All of them produce the same `ExtractedReceipt`, so nothing else
in the app changes.

| Engine | Billed by | Notes |
|---|---|---|
| `openrouter` | your OpenRouter credit | One gateway in front of many providers. Reports the real cost of every call, so the Costs page shows what you were actually charged rather than an estimate. The model must support vision and structured outputs. |
| `claude` | Anthropic, directly | What the prompt was written and tuned against. Uses schema-validated output, prompt caching and adaptive thinking. A Claude Pro/Max subscription does **not** cover it. |
| `tesseract`, `ollama` | nothing | Stubs. See `app/extraction/local.py`. |

### Finding a cheaper model

`scripts/list_models.py` reads OpenRouter's catalogue, keeps only the models that accept
images **and** support strict structured outputs, and ranks them by what one receipt would
cost at your own token counts:

```bash
python scripts/list_models.py --in 3000 --out 1200
```

Take the token numbers from the Costs page rather than the defaults — the per-receipt
figure is just tokens x rate, so an unexpected bill is nearly always an unexpected input
token count, and the photo is most of the input. `MAX_IMAGE_EDGE=1280` roughly halves it.

Before deploying, check a key and model actually work together on a real image:

```bash
EXTRACTOR=openrouter OPENROUTER_API_KEY=sk-or-... \
    python scripts/try_extract.py tests/fixtures/receipts/synthetic_tesco.jpg
```

It prints the parsed lines, the real cost, and whether the arithmetic balanced. One API
call, no database, no containers.

**If the model returns prose instead of the structure**, it does not honour strict
structured outputs — try another. That is the one failure mode this route has that going
direct to Anthropic does not.

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
