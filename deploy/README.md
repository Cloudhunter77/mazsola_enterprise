# Installing on TrueNAS SCALE

Tested against the Docker-based app system (TrueNAS 24.10 "Electric Eel" and later).
TrueNAS 25.10 requires the top-level `services:` key in custom YAML, which
`docker-compose.yaml` here already has.

## 1. Datasets

**Datasets → Add Dataset**, under your pool, create:

| Dataset | Holds |
|---|---|
| `apps/mazsola/images` | the receipt photos |
| `apps/mazsola/pgdata` | the PostgreSQL data directory |
| `apps/mazsola/backups` | nightly database dumps (optional) |

Set the owner of all three to UID **568**, GID **568** (the `apps` user) — the app runs
as that user, and the containers cannot write otherwise:

```sh
chown -R 568:568 /mnt/tank/apps/mazsola
```

Snapshot `apps/mazsola` on whatever schedule you like; with the backup script below, one
snapshot covers both the photos and the database.

## 2. The values you need

Run these anywhere with a shell (they never leave your machine):

```sh
openssl rand -hex 32          # SECRET_KEY
openssl rand -hex 24          # API_KEY, for the phone shortcut
openssl rand -hex 16          # the database password
python scripts/hash_password.py   # APP_PASSWORD_HASH - prompts, echoes nothing
```

And an API key from <https://console.anthropic.com> for `ANTHROPIC_API_KEY`.

## 3. Install

**Apps → Discover Apps → ⋮ → Install via YAML.** Name it `mazsola`, paste
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

## 4. On your phone

Open `http://<nas>:8088` over your VPN and add it to the home screen (iOS: Share →
Add to Home Screen; Android: menu → Install app). It then opens full-screen, and
**Fotó készítése** goes straight to the camera.

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

## 5. Backups

Copy `scripts/backup.sh` to `/mnt/tank/apps/mazsola/`, then **System → Advanced →
Cron Jobs**, daily as root:

```sh
sh /mnt/tank/apps/mazsola/backup.sh
```

It writes a compressed `pg_dump` into the `backups` dataset and keeps the last 14. Check
the container name first (`docker ps | grep mazsola`) and set `DB_CONTAINER` if it is not
`mazsola-db-1`.

## 6. Updating

The image is built by GitHub Actions on every push and published to
`ghcr.io/cloudhunter77/mazsola:latest`. To update: **Apps → mazsola → ⋮ → Pull image**,
then restart. Schema migrations run automatically on start.

## Troubleshooting

**The app container restarts in a loop.** Almost always the database: check that
`DATABASE_URL`'s password matches `POSTGRES_PASSWORD`, and that `pgdata` is owned by
568:568. `docker logs mazsola-app-1` says which.

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
Below about 1000 the small print on thermal receipts starts to fail.
