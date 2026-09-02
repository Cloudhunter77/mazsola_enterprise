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
```

For `APP_PASSWORD_HASH`, run the hashing script inside the image you already pulled, so
there is nothing to install:

```sh
docker run --rm -it ghcr.io/cloudhunter77/mazsola:latest python scripts/hash_password.py
```

It prompts twice, echoes nothing, and prints two forms of the hash. **Use the
compose-safe one** — an Argon2 hash contains `$` characters, Docker Compose reads `$` as
the start of a variable substitution, and a raw hash pasted into the YAML is silently
corrupted so that every login fails with no clue why. The escaped form doubles each `$`,
which compose turns back into the original.

And an API key from <https://console.anthropic.com> for `ANTHROPIC_API_KEY`.

> A Claude Pro or Max subscription does **not** cover this. The subscription and the API
> are billed separately — you need a Console account with credits on it. The minimum
> top-up lasts a long time at this app's usage; see the cost table in the main README.

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
docker pull ghcr.io/cloudhunter77/mazsola:latest
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
git clone https://github.com/Cloudhunter77/mazsola_enterprise.git /mnt/tank/apps/mazsola/src
cd /mnt/tank/apps/mazsola/src && docker build -t mazsola:local .
```

Then in the compose file below, change the app's `image:` to `mazsola:local` and add
`pull_policy: never` beside it. Updating then means `git pull` and building again.

Making the GHCR package public is a third option, but the image contains the application
source, so it would publish the code that this private repository is keeping private.

## 4. Install

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

## 5. On your phone

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

## 6. Backups

Copy `scripts/backup.sh` to `/mnt/tank/apps/mazsola/`, then **System → Advanced →
Cron Jobs**, daily as root:

```sh
sh /mnt/tank/apps/mazsola/backup.sh
```

It writes a compressed `pg_dump` into the `backups` dataset and keeps the last 14. Check
the container name first (`docker ps | grep mazsola`) and set `DB_CONTAINER` if it is not
`mazsola-db-1`.

## 7. Updating

The image is built by GitHub Actions on every push and published to
`ghcr.io/cloudhunter77/mazsola:latest`. To update: **Apps → mazsola → ⋮ → Pull image**,
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
