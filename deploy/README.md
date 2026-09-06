# Installing on TrueNAS SCALE

> Handing the install to another Claude session instead? `COWORK_PROMPT.md` next to this
> file is a self-contained brief covering the same ground, and `COWORK_UPDATE.md` is the
> equivalent for updating an install that is already running.

Tested against the Docker-based app system (TrueNAS 24.10 "Electric Eel" and later).
TrueNAS 25.10 requires the top-level `services:` key in custom YAML, which
`docker-compose.yaml` here already has.

## 1. Datasets

**Datasets → Add Dataset**, under your pool, create:

| Dataset | Holds |
|---|---|
| `apps/receipt-tracker/images` | the receipt photos |
| `apps/receipt-tracker/pgdata` | the PostgreSQL data directory |
| `apps/receipt-tracker/backups` | nightly database dumps (optional) |

Set the owner of all three to UID **568**, GID **568** (the `apps` user) — the app runs
as that user, and the containers cannot write otherwise:

```sh
chown -R 568:568 /mnt/tank/apps/receipt-tracker
```

Snapshot `apps/receipt-tracker` on whatever schedule you like; with the backup script below, one
snapshot covers both the photos and the database.

## 2. The values you need

Run these anywhere with a shell (they never leave your machine):

```sh
openssl rand -hex 32          # SECRET_KEY
openssl rand -hex 24          # API_KEY, for the phone shortcut
openssl rand -hex 16          # the database password
```

For `APP_PASSWORD_HASH`, run the hashing script inside the image you already pulled, so
there is nothing to install:

```sh
docker run --rm -it ghcr.io/cloudhunter77/receipt-tracker:latest python scripts/hash_password.py
```

It prompts twice, echoes nothing, and prints two forms of the hash. **Use the
compose-safe one** — an Argon2 hash contains `$` characters, Docker Compose reads `$` as
the start of a variable substitution, and a raw hash pasted into the YAML is silently
corrupted so that every login fails with no clue why. The escaped form doubles each `$`,
which compose turns back into the original.

And a key for whichever extraction engine you chose:

- **OpenRouter** (the default in the compose file): a key from
  <https://openrouter.ai/keys>, as `OPENROUTER_API_KEY`.
- **Anthropic directly**: a key from <https://console.anthropic.com>, as
  `ANTHROPIC_API_KEY`. A Claude Pro or Max subscription does **not** cover this — the
  subscription and the API are billed separately.

Before installing, check the key and model actually work on a real image. One API call,
nothing else needed:

Load the key into your shell first, so it never reaches a command line or your history —
run these one at a time, pasting the key at the silent prompt:

```sh
read -rs OPENROUTER_API_KEY && export OPENROUTER_API_KEY
```
```sh
docker run --rm -e EXTRACTOR=openrouter -e OPENROUTER_API_KEY ghcr.io/cloudhunter77/receipt-tracker:latest python scripts/try_extract.py tests/fixtures/receipts/synthetic_tesco.jpg
```

`-e OPENROUTER_API_KEY` with no `=` passes the variable through from your shell.

It prints the lines it read, the real cost, and whether the totals balanced. If the model
answers with prose instead of structured data, it does not support strict structured
outputs — pick another model and try again.

## 3. Let the NAS pull the image

This repository is private, so the image GitHub Actions publishes to GHCR is private
too, and a plain `docker pull` from the NAS fails with `denied`. Pick one of these once,
before installing.

**Either — log the NAS in to GHCR (keeps everything private).** Create a token at
<https://github.com/settings/tokens> (classic) with only the **`read:packages`** scope.
Then over SSH on the NAS, run these **one at a time** — the second prompts for the
password, so paste the token there rather than putting it on a command line:

```sh
sudo -i
docker login ghcr.io -u Cloudhunter77
docker pull ghcr.io/cloudhunter77/receipt-tracker:latest
```

`sudo -i` matters: the Apps system pulls images as root and reads
`/root/.docker/config.json`. Logging in as your admin user writes to that user's home
instead, and the pull would still be denied at install time even though the login said
it succeeded.

The credentials persist across reboots, so every later pull and update just works. A
major TrueNAS upgrade builds a new boot environment and may not carry them over — if a
pull is denied after one, just run the login again. To undo: `docker logout ghcr.io`.

**Or — build the image on the NAS instead**, and skip the registry entirely:

```sh
git clone https://github.com/Cloudhunter77/mazsola_enterprise.git /mnt/tank/apps/receipt-tracker/src
cd /mnt/tank/apps/receipt-tracker/src && docker build -t receipt-tracker:local .
```

Then in the compose file below, change the app's `image:` to `receipt-tracker:local` and add
`pull_policy: never` beside it. Updating then means `git pull` and building again.

Making the GHCR package public is a third option, but the image contains the application
source, so it would publish the code that this private repository is keeping private.

## 4. Install

**Apps → Discover Apps → ⋮ → Install via YAML.** Name it `receipt-tracker`, paste
`deploy/docker-compose.yaml`, and before saving:

- replace both `/mnt/tank/...` paths with your pool name,
- replace every `CHANGE_ME_*` value,
- use the **same** database password in `POSTGRES_PASSWORD` and in `DATABASE_URL`.

Save. The first start pulls the image, applies the schema migrations and seeds the
Hungarian category tree — that takes a minute or two. The app is then at
`http://<nas>:8088`.

Check it came up:

```sh
curl http://<nas>:8088/health
# {"status":"ok","database":true,"extractor":"claude","model":"claude-opus-5","worker":true}
```

## 5. On your phone

Open `http://<nas>:8088` over your VPN and add it to the home screen (iOS: Share →
Add to Home Screen; Android: menu → Install app). It then opens full-screen, and
**Fotó készítése** goes straight to the camera. **Tallózás** picks from the photo library
instead, for receipts you have already photographed.

A receipt too long to fit one legible frame goes up in sections: take the first photo, then
**📷 További rész** for each further one, top to bottom with a few lines of overlap, and
**Feldolgozás** when the whole receipt is covered. Up to eight sections make one receipt;
they are read together as a single document.

### iOS Shortcut (optional)

For a one-tap capture from the lock screen or Action Button:

1. Shortcuts → **+** → Add Action → **Take Photo**.
2. Add Action → **Get Contents of URL**:
   - URL: `http://<nas>:8088/api/receipts?source=shortcut`
   - Method: **POST**
   - Headers: `X-API-Key` = the `API_KEY` you generated
   - Request Body: **Form**, one field named `file` of type *File*, value **Photo**
     (the output of the previous step)
3. Name it "Blokk", and add it to the Home Screen or Action Button.

The upload returns immediately; the reading happens on the NAS. Open the app later to
review anything flagged.

## 6. Things that never printed a receipt

Two extra ways into the same database, both reachable from the **Tábla** tab:

- **Kézi** — a receipt you lost but remember. Shop, date, one or more lines. It is saved
  as already confirmed and counts in every statistic.
- **Előfizetések** — Spotify, YouTube and the like. Amount, day of the month, start date;
  each month's charge then appears on its own. The app generates anything already due when
  you save the rule, and checks hourly after that. Running it twice never charges twice —
  the periods are keyed so a repeat is a no-op.

A subscription set to the 31st charges on the last day of a short month rather than
skipping it. Pausing a rule keeps its history; deleting the rule also keeps the receipts it
generated.

## 7. Backups

Copy `scripts/backup.sh` to `/mnt/tank/apps/receipt-tracker/`, then **System → Advanced →
Cron Jobs**, daily as root:

```sh
sh /mnt/tank/apps/receipt-tracker/backup.sh
```

It writes a compressed `pg_dump` into the `backups` dataset and keeps the last 14. Check
the container name first (`docker ps | grep receipt-tracker`) and set `DB_CONTAINER` if it is not
`receipt-tracker-db-1`.

## 8. Updating

The image is built by GitHub Actions on every push and published to
`ghcr.io/cloudhunter77/receipt-tracker:latest`. To update: **Apps → receipt-tracker → ⋮ → Pull image**,
then restart. Schema migrations run automatically on start.

## Troubleshooting

**"SECRET_KEY is still a placeholder from the repository".** The app refuses to start
rather than run with a signing key that is published in this repository — anyone who
could reach it would be able to forge a login session. Generate one with
`openssl rand -hex 32` and set it. The same guard rejects any key under 32 characters.

**"denied" or "manifest unknown" when pulling the image.** The GHCR package is private
because the repository is; see step 3 above.

**The app container restarts in a loop.** Almost always the database: check that
`DATABASE_URL`'s password matches `POSTGRES_PASSWORD`, and that `pgdata` is owned by
568:568. `docker logs receipt-tracker-app-1` says which.

**Postgres will not initialise.** It refuses a non-empty data directory. The compose file
sets `PGDATA` one level down inside the mount for exactly this reason — keep that line.

**Uploads stay "Sorban áll" forever.** The worker is not running or cannot reach the API.
Check `/health` shows `"worker": true`, and look for `ANTHROPIC_API_KEY is not set` in the
logs. Receipts are not lost — fix the key and use **Újrafeldolgozás**.

**Everything lands in "Ellenőrzendő".** The reading is not balancing. Open one and compare
against the photo; if the totals are right but flagged, the receipt layout may need a
prompt adjustment in `app/extraction/prompt.py`. If the numbers are genuinely wrong, try
`EXTRACTOR_MODEL=claude-opus-5` (if you had moved to a cheaper model) and reprocess.

**Photos are huge and extraction is slow or pricey.** Lower `MAX_IMAGE_EDGE` to `1280`.

Note that `MAX_IMAGE_EDGE` caps the **longest** edge, and a receipt is a tall ribbon: a
1200x3757 photo fitted to 1600 leaves only 511px of width for ~40 characters a line. It is
the width that carries legibility, so `MIN_IMAGE_WIDTH` (default `800`) is a floor that
overrides the cap for tall photos. It only affects receipts that would otherwise be
squeezed — an ordinary photo is untouched — and on the one that needed it, the image went
from ~1090 to ~2670 tokens. Set it to `0` for the old longest-edge-only behaviour.
Photographing a long receipt in sections is the cheaper fix: each section is nearer square,
so the cap never bites.

**Extraction costs more per receipt than the model's list price suggests.** Look at the
token columns on **Felismerési költség** before changing model: cost is tokens x rate, and
the photo is most of the input. `MAX_IMAGE_EDGE=1280` roughly halves the input tokens. To
compare models on your own numbers rather than headline prices:

```sh
docker run --rm ghcr.io/cloudhunter77/receipt-tracker:latest \
    python scripts/list_models.py --in <your input tokens> --out <your output tokens>
```

It lists only models that can do both vision and strict structured outputs, cheapest first
for this workload. Try any candidate on the sample receipt before switching to it.

**A long receipt comes out unreadable.** Photograph it in sections instead: press
**📷 További rész** on the capture screen for each one, working top to bottom with a few
lines of overlap between them, then **Feldolgozás**. They are read together as one receipt,
and the review screen lets you page between the sections.
