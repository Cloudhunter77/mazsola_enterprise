# Handover prompt for updating a running install

For a NAS that already has Receipt Tracker installed and working. If you are installing it
for the first time, use `COWORK_PROMPT.md` instead.

Paste everything below the line into Claude Cowork (or any new Claude session with shell
access to the NAS). It is written to be understood cold.

---

I already run a self-hosted app called **Receipt Tracker** on my TrueNAS SCALE NAS. It is
installed, healthy, and has successfully read a real Hungarian receipt. A new version has
been published and I want you to update to it and then help me with two follow-ups.

I will be at the keyboard the whole time. Stop and tell me if anything does not match what
is described here.

## What it is

Photograph a Hungarian till receipt on my phone; the app reads the shop, date, line items,
ÁFA rates and total with a vision model, checks the arithmetic balances, and stores it in
PostgreSQL. It then shows spending statistics, per-product price history, and which shop is
cheapest for my usual basket.

- Repository: `https://github.com/Cloudhunter77/mazsola_enterprise` (private)
- Branch: `claude/receipt-expense-tracker-mux58h`
- Image: `ghcr.io/cloudhunter77/receipt-tracker:latest` (private GHCR package; this NAS is
  already logged in to GHCR as root)
- TrueNAS app name: `receipt-tracker`, containers `receipt-tracker-app-1` and
  `receipt-tracker-db-1`, web UI on port 8088, reachable over my VPN only
- Deployment guide in the repo: `deploy/README.md`

## Ground rules

Each of these has already cost me time:

1. **Give me one command at a time.** My shell is zsh over the TrueNAS web console. A
   multi-line block pasted at once gets its newlines collapsed and the commands run into
   each other. One command, I run it, I paste you the output.
2. **Never put a secret on a command line, and never print one back to me.** If I paste a
   secret into the chat by mistake, tell me immediately to revoke it.
3. **I am `truenas_admin`, not root.** Anything touching Docker needs `sudo -i` first.
4. **Prefer the TrueNAS web UI for anything TrueNAS owns** (datasets, apps, cron).
5. **Do NOT run `chown -R 568:568` over the app directory.** This already broke my
   database once. That command is in the *install* guide and applies only to a fresh,
   empty dataset. PostgreSQL sets its own internal ownership inside `pgdata`, and
   recursively chowning it caused `InsufficientPrivilegeError` on `pg_filenode.map`.
   Nothing in this update needs a permission change. (If it somehow happens again: the
   fix is to restart the `db` container, whose entrypoint re-asserts ownership as root,
   and then restart `app`.)
6. **Verify each step before moving on**, and tell me what you expect so I can say if it
   differs.

## What is new in this version

- **Upload from the photo library**, not only the camera.
- **Multi-part receipts**: a receipt too long to photograph legibly in one frame can be
  captured as up to eight overlapping photos and is read as a single document.
- **A database migration** creating a `receipt_images` table, which backfills every
  existing receipt as a one-part receipt. It runs automatically at startup.
- **Token counts on the Costs page**, and `scripts/list_models.py` for comparing models.

## Step 1 — Update the image

**Apps → receipt-tracker → ⋮ → Pull image**, then restart the app. No compose changes are
needed for this step, and no dataset or secret changes at all.

The first start after the pull applies the migration. Give it a minute, then:

```
curl http://localhost:8088/health
```

Expect `{"status":"ok","database":true,...,"worker":true}`.

Then confirm the migration actually ran:

```
docker logs receipt-tracker-app-1 2>&1 | tail -40
```

Expect a line reading `database schema is up to date` and no traceback. The app does not
serve traffic until migrations succeed, so a healthy `/health` is already good evidence.

## Step 2 — Confirm nothing was lost

My existing receipts must still be there and still openable.

1. Open `http://<nas-ip>:8088` over my VPN.
2. Check that the receipts I already had are listed.
3. Open one and confirm the photo still displays beside the parsed lines.

Existing receipts should each show as a single-page receipt. If a receipt list is empty or
an image 404s, stop and tell me before doing anything else.

## Step 3 — Work out why extraction costs what it does

Three receipts cost me about **$0.15** — roughly $0.05 each. I thought I was using Haiku,
which should be about $0.009. So either I am not on the model I think, or the token counts
are higher than expected. Find out which; do not just switch me to something cheaper.

**First, the most likely cause.** The two extraction engines read *different* environment
variables, and setting the wrong one fails silently:

| Engine | Reads |
|---|---|
| `EXTRACTOR=openrouter` | **`OPENROUTER_MODEL`** |
| `EXTRACTOR=claude` | `EXTRACTOR_MODEL` |

I am on OpenRouter. If I set `EXTRACTOR_MODEL` expecting it to take effect, it was ignored
and I stayed on the compose default `anthropic/claude-sonnet-4.5` — which at $3/$15 per
million tokens would land close to the $0.05 I actually paid. Check with:

```
docker exec receipt-tracker-app-1 env | grep MODEL
```

The **Felismerési költség** page also records the model each extraction actually used, per
month. That page is the authority — it reports what OpenRouter charged, not an estimate.

**Then get my real token counts.** That page now has *Token be* and *Token ki* columns:
average input and output tokens per receipt. Cost is tokens x rate, so these explain the
bill. Tell me both numbers.

**Then rank the models on my numbers**, substituting the token counts you just read:

```
docker run --rm ghcr.io/cloudhunter77/receipt-tracker:latest python scripts/list_models.py --in 3000 --out 1200
```

It reads OpenRouter's live catalogue, keeps only models that support **both** vision and
strict structured outputs (the app needs both), and ranks them by what one of my receipts
would cost. No API key needed. If the NAS cannot reach openrouter.ai, run it from another
machine with Python 3.11+ and the repo checked out.

**Before switching to any candidate**, try it on the sample receipt bundled in the image:

```
read -rs OPENROUTER_API_KEY && export OPENROUTER_API_KEY
```

I paste the key at the silent prompt. Then, with `<id>` being the candidate:

```
docker run --rm -e EXTRACTOR=openrouter -e OPENROUTER_API_KEY -e OPENROUTER_MODEL=<id> ghcr.io/cloudhunter77/receipt-tracker:latest python scripts/try_extract.py tests/fixtures/receipts/synthetic_tesco.jpg
```

`-e OPENROUTER_API_KEY` with **no `=`** passes the variable through from my shell; writing
`-e OPENROUTER_API_KEY=<key>` would put the key on the command line.

That fixture is synthetic, so the correct answer is known: total **5230 Ft**, rounding
**−2**, **six** goods lines, plus one deposit (`BETÉTDÍJ`), one discount
(`KEDVEZMÉNY AKCIÓ`) and one rounding line (`KEREKÍTÉS`), and the arithmetic balancing. A
model that gets that wrong is not cheaper, whatever it costs. If it answers with prose
instead of structured data, it does not honour strict structured outputs — try another.

**To switch**, edit `OPENROUTER_MODEL` in the app's YAML (**Apps → receipt-tracker → ⋮ →
Edit**) and restart. Nothing else changes.

**One free saving regardless of model**: `MAX_IMAGE_EDGE: "1280"` (from `1600`) roughly
halves the input tokens, and the photo is most of the input. Below about 1000 the small
print on thermal receipts starts to fail. Worth trying after we know the token counts.

## Step 4 — Test a long receipt captured in sections

This is the part I most want checked, because it has only been tested with synthetic
images and a stubbed engine. Whether a real model reads overlapping photos without
double-counting is genuinely unproven.

On my phone, over the VPN:

1. Take a long receipt — the kind where one photo makes the small print unreadable.
2. **📷 Fotó készítése** for the top section.
3. **📷 További rész** for each following section, working down the receipt and leaving a
   few lines of **overlap** between consecutive photos.
4. **Feldolgozás**.

It should become **one** receipt, not several. Then open it and check, in this order:

- Is every line present exactly once? A line visible in two photos being transcribed
  **twice** is the specific failure mode to look for.
- Does the total match the receipt?
- Does the review screen offer `1. rész / 2. rész` buttons, and does each show the right
  section?

If it lands in **Ellenőrzendő**, that is the arithmetic check working, not a crash — the
reason is shown at the top. Tell me the reason and what you see in the lines.

Also try **🖼️ Tallózás** once, to confirm picking an existing photo from the library works.

## Finally

Tell me plainly:

- whether the update went through cleanly and my old receipts survived,
- which model I was **actually** being billed for, and my real token counts,
- what you would switch to and why, on those numbers,
- and how the multi-part read behaved on a real receipt — especially any duplicated line.

If anything needs a code change rather than configuration, say so rather than working
around it; I have a session that can make it.
