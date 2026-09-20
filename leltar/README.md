# Leltár

Photograph what you own; a vision model names it, and you approve the name. Self-hosted,
built for TrueNAS SCALE, in Hungarian.

The tedious part of a home inventory is not the photographing — it is typing "fekete bőr
irodai forgószék" four hundred times. So you point the camera at a shelf, and the app comes
back with a list of names you tap through: accept, tap an alternative, or retype. What
survives that is the inventory. For insurance, for moving house, and for finding the thing
you know you own.

## How it works

```
phone camera
      │  POST /api/photos  (+ which room you are standing in)
      ▼
 app container ──────────────► vision model (Claude by default)
 FastAPI + SPA + worker              │
      │                              ▼
      ▼                   draft items, one per object found
 PostgreSQL                 nothing counts until you approve it
```

Two containers, no queue service. Job state lives in the database, so a restart resumes
rather than loses work.

## What it refuses to do

A vision model will confidently answer any question you ask it, and three of the obvious
questions have answers that are worse than useless. So the app does not ask them, and
`leltar/extraction/rules.py` throws away the ones that arrive anyway:

- **It will not infer a brand.** Asked what make a laptop is, a model says Dell, because
  most laptops that shape are. Nothing in the photograph said so. `brand` is kept only
  when the model reports that the text was legible in the frame — and an inferred one is
  dropped, with `unverifiable_brand` shown against the entry so you know it was dropped
  rather than never guessed. Same rule for serial numbers. On an insurance list, an
  invented brand is a claim you cannot support.
- **It will not price to the forint.** Values are a range, and a wide range is an honest
  answer. The midpoint exists so the statistics have something to add up, and the summary
  says how many items the total actually rests on.
- **It will not inventory the building.** Walls, radiators, doors, fitted worktops and the
  ceiling light are all plainly visible and none of them are things you own in the sense
  that matters. Nor is food, nor rubbish.

And two rules about names, because a name you cannot search for is a row you will never
find again: "tárgy", "eszköz" and their friends are flagged as `generic_name`, and a
category the app does not know is filed under **Egyéb** rather than trusted.

Everything flagged still lands in the review queue with the rest. One bad guess in a
photograph never discards the eight good ones.

## What ends up in the inventory

Only what you confirmed. A draft is the model's opinion, and a total that includes
opinions is the number nobody can use — so drafts are counted separately, as a queue
depth. That is also what makes the **Pontosság** panel meaningful: the name the model
suggested is kept next to the name you settled on, so the app can tell you what share of
its guesses you accepted unchanged. It is the only honest measure it can take of itself.

## Spending that never took a photograph

**Kézi rögzítés** — type in what you did not photograph: what is in the loft, what is lent
out, what lives in a case. It is stored confirmed rather than queued, because you named
it, and it is marked `manual` so it never flatters the accuracy figure.

## Getting started

**On the NAS:** see [`deploy/README.md`](deploy/README.md).

**Locally:**

```bash
cp .env.example .env          # add your ANTHROPIC_API_KEY
docker compose -f docker-compose.dev.yaml up --build
open http://localhost:8001
```

**Without Docker:**

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
cd web && npm install && npm run build && cd ..
export DATABASE_URL=postgresql+asyncpg://leltar:leltar@localhost:5433/leltar
export ANTHROPIC_API_KEY=sk-ant-...
export AUTH_DISABLED=true     # local only
.venv/bin/uvicorn leltar.main:app --reload --port 8001
```

Migrations, the category list and a starter set of rooms are applied at startup; there is
no separate setup step.

Want to see the screens before you have photographed anything?

```bash
python scripts/seed_demo.py --yes     # plausible contents for four rooms
python scripts/seed_demo.py --clear   # removes exactly what it created
```

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://leltar:leltar@db:5432/leltar` | |
| `DATA_DIR` | `/data` | Where the photographs are stored |
| `IDENTIFIER` | `claude` | `claude` or `ollama` (a stub; see `leltar/extraction/local.py`) |
| `IDENTIFIER_MODEL` | `claude-sonnet-5` | `claude-haiku-4-5` costs about a fifth as much |
| `IDENTIFIER_EFFORT` | `low` | Naming a visible object does not repay deliberation |
| `ANTHROPIC_API_KEY` | – | A Console key, not a Pro/Max subscription |
| `MAX_IMAGE_EDGE` | `1280` | The main cost lever; images bill at `w×h/750` tokens |
| `MAX_ITEMS_PER_PHOTO` | `12` | Past this, the extra rows are background clutter |
| `BUILD_COMMIT` | – | Stamped by CI; shown on the Rendszer page so an update can be verified |
| `SECRET_KEY` | – | Signs the session cookie |
| `APP_PASSWORD_HASH` | – | `python scripts/hash_password.py` |
| `API_KEY` | – | For an iOS Shortcut's `X-API-Key` header |
| `AUTH_DISABLED` | `false` | Local development only |
| `WORKER_ENABLED` | `true` | Off means photos queue but are not read |

## What it costs to run

Identification is the only running cost. A downscaled photograph is about 1.6k input
tokens, and a reply naming a handful of objects about 700 output tokens:

| Model | Per photograph | 500 photographs |
|---|---|---|
| `claude-opus-5` | ~$0.026 | ~$13 |
| `claude-sonnet-5` | ~$0.010 | ~$5 |
| `claude-haiku-4-5` | ~$0.005 | ~$2.50 |

Cataloguing a house is a few hundred photographs once, then a handful a year — so this is
a one-off cost of a few dollars rather than a subscription. The app records the real token
cost of every call and shows it under **Rendszer → Felismerési költség**, per photograph
*and* per confirmed item. The second figure is the one worth watching: a photo of a whole
shelf costs the same as a photo of one chair.

Before deploying, check that a key and a model actually work together on a real image:

```bash
ANTHROPIC_API_KEY=sk-ant-... python scripts/try_identify.py tests/fixtures/shelf.jpg
```

One API call, no database, no containers. It prints what the model said *and* what the
rules did to it, so a dropped brand shows up there rather than weeks later.

## Moving off the API later

`leltar/extraction/base.py` defines the whole contract: image bytes in, an `IdentifiedPhoto`
out. `claude.py` is one implementation; `local.py` sketches an Ollama engine with the
intended shape. Nothing else in the app knows which engine ran, so swapping is a new file
plus `IDENTIFIER=...`. Keep the rules in place with a smaller model, not less — a local 7B
model invents brands far more readily than Claude does.

## Tests

```bash
pytest -q                # needs TEST_DATABASE_URL pointing at a PostgreSQL
pytest -m live -s        # hits the real API, costs a few cents, needs ANTHROPIC_API_KEY
```

The default suite covers the rules, ingest deduplication, the worker's retry and failure
handling, the API, the statistics, and that the migrations and the models still describe
the same database. The live suite is the one that measures whether identification is
actually any good — drop photographs of your own things into `tests/fixtures/` and they
are picked up automatically.

## Relationship to the receipt scanner

This repository holds two apps that share a house style and nothing else. They have
separate images, databases, ports, datasets and CI workflows; installing, updating or
removing one does nothing to the other. Where the code looks similar — the auth module,
the image preprocessing, the version panel — it is deliberately copied rather than shared,
because a shared library between two separately deployed apps is how one app's update
breaks the other.

## Licence

Personal project; do as you like with it.
