# Leltár

Photograph what you own; a vision model names it, and you approve the name. Self-hosted,
built for TrueNAS SCALE, in Hungarian.

A searchable database of the things in your house, with a picture of each one. The tedious
part of building one is not the photographing — it is typing "fekete bőr irodai forgószék"
four hundred times. So you point the camera at a shelf, and the app comes back with a list
of names you tap through: accept, tap an alternative, or retype. What survives that is the
catalogue.

It is a catalogue, not a valuation. The model is never asked what anything is worth — the
counts are of things, and the one value field is optional and typed in by you, for the
handful of items where it matters.

## How it works

```
phone camera
      │  POST /api/photos  (+ which room, + one thing or a whole shelf)
      ▼
 app container ──────────────► vision model (Claude, or anything on OpenRouter)
 FastAPI + SPA + worker              │
      │                              ▼
      │                    draft items, one per object found,
      │                    each with a box saying where it is
      ▼                              │
 PostgreSQL ◄────────────────────────┘
 + a picture per item, cut from the photograph at that box
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
- **It is not asked what anything is worth.** A price guessed from a photograph is a
  number that looks like information and is not one, and it costs output tokens on every
  single call. The app counts things instead.
- **It will not inventory the building.** Walls, radiators, doors, fitted worktops and the
  ceiling light are all plainly visible and none of them are things you own in the sense
  that matters. Nor is food, nor rubbish.

And two rules about names, because a name you cannot search for is a row you will never
find again: "tárgy", "eszköz" and their friends are flagged as `generic_name`, and a
category the app does not know is filed under **Egyéb** rather than trusted.

Everything flagged still lands in the review queue with the rest. One bad guess in a
photograph never discards the eight good ones.

## A picture of every thing

A row of text is not an inventory entry you can use. Which of the two drills is this?
Which blue box? So every item carries its own picture:

- **Photograph one object** ("Egy tárgy" on the capture screen) and that photograph is the
  item's picture. The model is told the frame has one subject, so it names the drill and
  not the workbench under it.
- **Photograph a whole shelf** ("Polc, szoba") and the model also returns a box around each
  object it names. Each box is cut out of the **original** photograph - not the downscale
  that was sent to the API - so eight things photographed at once become eight items with
  eight distinct pictures, for the price of reading one image.
- **Add more pictures later**, on the item's own page: the serial plate, the damage, the
  thing out of its case. Any of them can be made the one the list shows.

A box is optional, and asking for one is where a model will most happily invent: it will
always produce four numbers. So a box that is inside out gets straightened, one that is a
pinprick or the entire frame is discarded, and an item whose box did not survive simply
gets the whole photograph as its picture - visibly wider, never wrong. The review screen
shows each crop next to its name, which is where a box on the wrong object is obvious.

## Finding things again

A catalogue of a whole household is only as good as its search, so the search is built for
how people actually type on a phone:

- **Accents are optional.** `bogre` finds the *bögre*, `funyiro` finds the *fűnyíró*.
  Nobody is going to long-press for an umlaut while standing in the garage.
- **Words in any order, and each one narrows.** `fekete furo` finds the black drill, not
  every black thing and every drill.
- **It looks in the name, the brand, the model, the description, the serial number and
  your notes** — all folded into one indexed column, kept in step by the model itself so
  no write path can forget to update it.

**A place means everything inside it.** Places nest — *Garázs › Fém polc › Kék doboz* — and
asking for the garage shows what is in the boxes in the garage. Anything else would make
the tree worse than a flat list of rooms.

## What ends up in the catalogue

Only what you confirmed. A draft is the model's opinion, and a count that includes
opinions moves every time the model has one — so drafts are counted separately, as a queue
depth. That is also what makes the **Pontosság** panel meaningful: the name the model
suggested is kept next to the name you settled on, so the app can tell you what share of
its guesses you accepted unchanged. It is the only honest measure it can take of itself.

## Things that were never photographed

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
| `IDENTIFIER` | `claude` | `claude`, `openrouter`, or `ollama` (a stub) |
| `IDENTIFIER_MODEL` | `claude-sonnet-5` | `claude-haiku-4-5` costs about a fifth as much |
| `IDENTIFIER_EFFORT` | `low` | Naming a visible object does not repay deliberation |
| `ANTHROPIC_API_KEY` | – | Required when `IDENTIFIER=claude`; a Console key, not a Pro/Max subscription |
| `OPENROUTER_API_KEY` | – | Required when `IDENTIFIER=openrouter` |
| `OPENROUTER_MODEL` | – | No default on purpose; `python scripts/list_models.py` lists today's |
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
a one-off cost of a few dollars rather than a subscription. (Dropping the value estimate
took roughly a fifth off the output tokens, which is most of why these are lower than they
were.) The app records the real token
cost of every call and shows it under **Rendszer → Felismerési költség**, per photograph
*and* per confirmed item. The second figure is the one worth watching: a photo of a whole
shelf costs the same as a photo of one chair, and yields eight entries instead of one.

## Choosing an engine, and going cheaper

`IDENTIFIER` picks one. Both produce the same `IdentifiedPhoto`, so nothing else in the
app changes.

| Engine | Billed by | Notes |
|---|---|---|
| `claude` | Anthropic, directly | What the prompt was written and tuned against. Schema-validated output, prompt caching, adaptive thinking. A Claude Pro/Max subscription does **not** cover it. |
| `openrouter` | your OpenRouter credit | One gateway in front of many providers — Mistral, Qwen, Gemini and the rest. Reports the real cost of every call, so the costs page shows what you were actually charged rather than an estimate. The model must support vision **and** strict structured outputs. |
| `ollama` | nothing | A stub. See `leltar/extraction/local.py`. |

Naming a visible object is a much easier task than transcribing a receipt, so this is a
place where a cheap model can genuinely do the job. Which one is cheap this month is not
something a README can tell you, so the app asks:

```bash
python scripts/list_models.py                    # everything usable, cheapest first
python scripts/list_models.py --contains mistral # just one vendor's
```

It keeps only models that accept images **and** enforce a strict schema, and ranks them by
what one photograph would cost at your own token counts. `OPENROUTER_MODEL` has no default
precisely because that list changes faster than this file does.

**What changes with a weaker model, and what does not.** The rules are not a formality
here: a smaller model infers brands more readily, places boxes worse, and is more willing
to name something it cannot really see. None of that reaches the inventory — an unreadable
brand is dropped, a nonsense box is discarded, a shaky guess is flagged. So the cost of a
weaker model is more entries to correct, not a quietly wrong inventory. Measure it rather
than guess: photograph a week of real things, then read **Pontosság**. The share of names
you kept unchanged is what decides whether a cheaper model is actually cheaper, because
the typing is the cost this app exists to remove.

```bash
# one real call, before trusting a model with a house
OPENROUTER_API_KEY=sk-or-... IDENTIFIER=openrouter OPENROUTER_MODEL=<id> \
    python scripts/try_identify.py tests/fixtures/shelf.jpg
```

**If the model returns prose instead of the structure**, it does not honour strict
structured outputs — try another. That is the one failure mode this route has that going
direct to Anthropic does not.

Before deploying, check that a key and a model actually work together on a real image:

```bash
ANTHROPIC_API_KEY=sk-ant-... python scripts/try_identify.py tests/fixtures/shelf.jpg
```

One API call, no database, no containers. It prints what the model said *and* what the
rules did to it, so a dropped brand shows up there rather than weeks later.

## Moving off the API entirely

`leltar/extraction/base.py` defines the whole contract: image bytes in, an
`IdentifiedPhoto` out. `claude.py` and `openrouter.py` are two implementations; `local.py`
sketches an Ollama engine with the intended shape. Nothing else in the app knows which
engine ran, so a fully local setup is a new file plus `IDENTIFIER=...`. Keep the rules in
place with a smaller model, not less — a local 7B model invents brands far more readily
than Claude does.

## Tests

```bash
pytest -q                # needs TEST_DATABASE_URL pointing at a PostgreSQL
pytest -m live -s        # hits the real API, costs a few cents, needs ANTHROPIC_API_KEY
```

The default suite covers the rules, ingest deduplication, the worker's retry and failure
handling, the API, search and the place tree, the statistics, and that the migrations and
the models still describe the same database. The live suite is the one that measures whether identification is
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
