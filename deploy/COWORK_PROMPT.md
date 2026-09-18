# Handover prompt for a fresh install

For a NAS that does not have Receipt Tracker yet. To update one that is already running,
use `COWORK_UPDATE.md` instead - it skips the datasets and secrets, which do not change.

Paste everything below the line into Claude Cowork (or any new Claude session with shell
access to the NAS) to have it carry out the installation. It is written to be understood
cold, with no memory of how the project was built.

---

I need you to install a self-hosted app called **Receipt Tracker** on my TrueNAS SCALE
NAS. I will be at the keyboard the whole time. Work through this step by step, and stop
and tell me if anything does not match what is described here.

## What the app is

Photograph a Hungarian till receipt on my phone; the app reads the shop, date, line items,
ÁFA rates and total with a vision model, checks the arithmetic balances, and stores it in
PostgreSQL. It then shows spending statistics, per-product price history, and which shop
is cheapest for my usual basket.

- Repository: `https://github.com/Cloudhunter77/mazsola_enterprise` (private)
- Branch: `claude/receipt-expense-tracker-mux58h`
- Image: `ghcr.io/cloudhunter77/receipt-tracker:latest` (private GHCR package)
- Deployment guide in the repo: `deploy/README.md`
- Compose file to install: `deploy/docker-compose.yaml`
- It runs two containers: the app (FastAPI + web UI + extraction worker) and PostgreSQL 17.
- The web UI is in Hungarian. Reachable over my VPN only; not exposed to the internet.

## What is already done

Do not redo these:

- The NAS can pull the image. Be careful how you verify that: TrueNAS keeps registry
  credentials for the **Apps** subsystem separately from the `docker login` at the shell,
  and an app deploy reads only the former. A successful `docker pull` by hand therefore
  proves nothing about whether the app will start — verify by starting the app.
- CI is green and the image is published.

## Start by pulling the current image

Any image already on this NAS is stale and **known broken**. Two separate faults have
been fixed since, both of the same kind - something true of the repository was assumed
true of the published image:

- `ModuleNotFoundError: No module named 'httpx'`, because the Dockerfile kept its own
  dependency list that had drifted from pyproject.toml. Dependencies are now read from
  pyproject.toml at build time.
- `scripts/try_extract.py` could not find its sample receipt, because `tests/` was never
  copied into the image. It is now.

CI closes both classes before publishing: it starts the built image, checks every module
imports, and asserts that every script and fixture path the documentation tells you to
run actually exists inside the image. Pull before anything else:

```
docker pull ghcr.io/cloudhunter77/receipt-tracker:latest
```

If you still see a `ModuleNotFoundError` after pulling, the pull did not take - check the
image digest rather than assuming. And note that packages named `httpx2` and `httpcore2`
appearing in the image are **correct, not typos**: the Anthropic SDK v1 is built on them.
Do not "fix" those.

## What is not done yet

- Creating the datasets.
- Generating the secrets.
- Filling in and installing the compose file.
- Any verification that extraction actually works.

## Ground rules

These exist because each one has already caused a problem:

1. **Give me one command at a time.** My shell is zsh over the TrueNAS web console. A
   multi-line block pasted at once gets its newlines collapsed and the commands run into
   each other. One command, I run it, I paste you the output.
2. **Never put a secret on a command line, and never print one back to me.** If you need
   me to supply a key, tell me where to paste it into a prompt or a file. If I paste a
   secret into the chat by mistake, tell me immediately to revoke it.
3. **I am `truenas_admin`, not root.** Anything touching Docker needs `sudo -i` first.
4. **Prefer the TrueNAS web UI for anything TrueNAS owns** (datasets, apps, cron). The
   shell is fine for file permissions and Docker. TrueNAS warns that unsupported config
   changes can break the system, and I would rather not find out.
5. **Verify each step before moving to the next**, and tell me what you expect to see so I
   can tell you if it differs.

## Step 1 — Find the pool name

The compose file has placeholder paths of the form `/mnt/tank/...`. Ask me to run
`zpool list` and use my actual pool name everywhere from then on.

## Step 2 — Datasets

Have me create these through **Datasets → Add Dataset** in the web UI:

- `apps/receipt-tracker/images` — the receipt photos
- `apps/receipt-tracker/pgdata` — the PostgreSQL data directory
- `apps/receipt-tracker/backups` — optional, for nightly database dumps

Then, in a root shell, ownership must be uid/gid **568** (the TrueNAS `apps` user); the
containers run as that user and cannot write otherwise:

```
chown -R 568:568 /mnt/<pool>/apps/receipt-tracker
```

## Step 3 — Generate four secrets

Have me run these one at a time and keep the outputs somewhere safe. They are not secret
from me, only from the chat log — it is fine for me to see them, so do not ask me to paste
them back to you.

```
openssl rand -hex 32
```
```
openssl rand -hex 24
```
```
openssl rand -hex 16
```

Those become `SECRET_KEY`, `API_KEY` and the database password respectively.

The fourth is my login password, hashed. It runs inside the image, so nothing needs
installing:

```
docker run --rm -it ghcr.io/cloudhunter77/receipt-tracker:latest python scripts/hash_password.py
```

It prompts twice, echoes nothing, and prints **two** forms of the hash. **Tell me to use
the compose-safe one** (the one where every `$` is doubled to `$$`). This matters: an
Argon2 hash contains five `$` characters, Docker Compose reads `$` as the start of a
variable substitution, and a raw hash pasted into the YAML is silently corrupted so that
every login fails with nothing in the logs to explain why.

I also have an **OpenRouter API key** (from openrouter.ai/keys) for the extraction engine.

## Step 4 — Smoke-test the extraction engine before installing anything

This runs one real API call against a sample receipt bundled in the image. No database, no
containers, nothing persistent. It is the cheapest way to find out whether my key and model
work together.

First, load the key into the shell without it touching the command line or shell history:

```
read -rs OPENROUTER_API_KEY && export OPENROUTER_API_KEY
```

I paste the key at the silent prompt. Then:

```
docker run --rm -e EXTRACTOR=openrouter -e OPENROUTER_API_KEY ghcr.io/cloudhunter77/receipt-tracker:latest python scripts/try_extract.py tests/fixtures/receipts/synthetic_tesco.jpg
```

Note `-e OPENROUTER_API_KEY` with **no `=`** — that passes the variable through from my
shell. Writing `-e OPENROUTER_API_KEY=<key>` would put the key on the command line.

**The correct answer is known**, because that fixture is synthetic: total **5230 Ft**,
rounding **−2**, **six** goods lines, plus one deposit (`BETÉTDÍJ`), one discount
(`KEDVEZMÉNY AKCIÓ`) and one rounding line (`KEREKÍTÉS`). It should also report that the
arithmetic balances. Check the output against that and tell me whether it matches.

If it fails:

- *"No endpoints found"* → the model id is wrong. The default is
  `anthropic/claude-sonnet-4.5`, which was a guess. Look up a current id on
  openrouter.ai/models that supports **both vision and structured outputs**, and retry
  with `-e OPENROUTER_MODEL=<id>` added.
- *"did not return the required structure"* or *"returned text rather than JSON"* → that
  model ignores strict structured outputs. Try a different one.
- *"Insufficient credits"* → I need to top up.

Do not proceed to the install until this passes.

## Step 5 — Fill in the compose file

Fetch `deploy/docker-compose.yaml` from the repo branch. Walk me through replacing:

- both `/mnt/tank/...` paths → my pool name
- `CHANGE_ME_DB_PASSWORD` → the 16-hex password, **in both places**: `POSTGRES_PASSWORD`
  and inside `DATABASE_URL`. They must match exactly or Postgres refuses every connection.
- `CHANGE_ME_OPENROUTER_KEY` → my OpenRouter key
- `OPENROUTER_MODEL` → whatever model passed step 4
- `CHANGE_ME_SECRET` → the 32-hex value
- `CHANGE_ME_PASSWORD_HASH` → the **compose-safe** hash from step 3
- `CHANGE_ME_API_KEY_FOR_SHORTCUT` → the 24-hex value

Leave `PGDATA: /var/lib/postgresql/data/pgdata` exactly as it is. Postgres refuses to
initialise into a non-empty directory and a TrueNAS dataset is never empty, so the data
must live one level down inside the mount.

The app deliberately **refuses to start** if `SECRET_KEY` is still a placeholder or is
shorter than 32 characters — it would otherwise be signing my login cookie with a value
published in a public repository. If you see that error, the key was not replaced properly.

## Step 6 — Install

**Apps → Discover Apps → ⋮ → Install via YAML.** Name it `receipt-tracker`, paste the
filled-in compose file, save.

First start pulls the image, applies database migrations and seeds a Hungarian category
tree. Give it a couple of minutes. Then check:

```
curl http://localhost:8088/health
```

Expected:

```
{"status":"ok","database":true,"extractor":"openrouter","model":"...","worker":true}
```

`"worker": true` matters — without it uploads queue forever.

If the app container restarts in a loop, get the logs (`docker logs receipt-tracker-app-1`).
The two most likely causes are a database password mismatch between the two places it
appears, and `pgdata` not being owned by 568:568.

## Step 7 — First real receipt

1. Open `http://<nas-ip>:8088` in a browser on my VPN. Log in with the password I hashed.
2. Photograph an actual Hungarian receipt and upload it through **Fotó készítése**.
3. Watch it go from *Sorban áll* → *Feldolgozás alatt* → either *Feldolgozva* or
   *Ellenőrzendő*.
4. Open it and compare every line against the photo. Tell me what it got wrong.

*Ellenőrzendő* means the arithmetic did not balance — that is the app working as intended,
not a failure. The reason is shown at the top of the receipt.

## Step 8 — Once it works

- On my phone: open the site over the VPN and add it to the home screen, so it opens
  full-screen and the capture button goes straight to the camera.
- Optional iOS Shortcut for one-tap capture — the recipe is in `deploy/README.md`,
  using the `API_KEY` from step 3 as an `X-API-Key` header.
- Optional nightly database backup — `scripts/backup.sh` plus a TrueNAS cron job, also
  described in `deploy/README.md`.

## Finally

Tell me plainly what worked, what did not, and anything you had to change from these
instructions. If extraction accuracy is poor on real Hungarian receipts, say so — the
prompt in `app/extraction/prompt.py` can be tuned, and a different model may read thermal
paper better.
