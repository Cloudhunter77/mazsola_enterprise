# Installing Leltár on TrueNAS SCALE

Tested against the Docker-based app system (TrueNAS 24.10 "Electric Eel" and later).
TrueNAS 25.10 requires the top-level `services:` key in custom YAML, which
`docker-compose.yaml` here already has.

**If you already run the receipt scanner from this repository:** this is a separate app
with a separate image, database, datasets and port. Nothing here touches that install, and
you never need to stop it. The one thing worth checking is that you edit *this* compose
file rather than that one — they look alike on purpose.

## 1. Datasets

**Datasets → Add Dataset**, under your pool, create:

| Dataset | Holds |
|---|---|
| `apps/leltar/photos` | the photographs |
| `apps/leltar/pgdata` | the PostgreSQL data directory |
| `apps/leltar/backups` | nightly database dumps (optional) |

Set the owner of all three to UID **568**, GID **568** (the `apps` user) — the app runs as
that user and the containers cannot write otherwise:

```sh
chown -R 568:568 /mnt/tank/apps/leltar
```

Snapshot `apps/leltar` on whatever schedule you like; with the backup script below, one
snapshot covers both the photographs and the database.

## 2. The values you need

Run these anywhere with a shell (they never leave your machine):

```sh
openssl rand -hex 32          # SECRET_KEY
openssl rand -hex 24          # API_KEY, for a phone shortcut
openssl rand -hex 16          # the database password
```

For `APP_PASSWORD_HASH`, run the hashing script inside the image, so there is nothing to
install:

```sh
docker run --rm -it ghcr.io/cloudhunter77/leltar:latest python scripts/hash_password.py
```

It prompts twice, echoes nothing, and prints two forms of the hash. **Use the compose-safe
one** — an Argon2 hash contains `$` characters, Docker Compose reads `$` as the start of a
variable substitution, and a raw hash pasted into the YAML is silently corrupted so that
every login fails with no clue why. The escaped form doubles each `$`, which compose turns
back into the original.

And an Anthropic key from <https://console.anthropic.com>, as `ANTHROPIC_API_KEY`. A
Claude Pro or Max subscription does **not** cover this — the subscription and the API are
billed separately.

Before installing, check the key and model actually work. One API call, nothing else
needed. Load the key into your shell first, so it never reaches a command line or your
history — run these one at a time, pasting the key at the silent prompt:

```sh
read -rs ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY
```
```sh
docker run --rm -e ANTHROPIC_API_KEY ghcr.io/cloudhunter77/leltar:latest python scripts/try_identify.py tests/fixtures/shelf.jpg
```

`-e ANTHROPIC_API_KEY` with no `=` passes the variable through from your shell. The image
ships with a synthetic shelf drawing as a fixture, so this works before you have
photographed anything. It prints what the model found, what the rules did to it, and the
real cost of the call.

## 3. Let the NAS pull the image

`ghcr.io/cloudhunter77/leltar` is a public package, so the pull is anonymous and there is
nothing to configure. That is deliberate, and worth knowing why, because getting it wrong
on the sister app cost a day:

TrueNAS keeps registry credentials in **two** separate places, and only one of them is
used when an app starts. `docker login` at the shell writes `/root/.docker/config.json`,
which is what a manual `docker pull` reads. The **Apps subsystem keeps its own registry
credentials** and does not read that file. So a successful `docker login` and a successful
manual `docker pull` prove *nothing* about whether the app will start: if the Apps store
has no entry for `ghcr.io`, every deploy fails `unauthorized` while every check you run by
hand succeeds. **Test by starting the app, never by pulling at the shell.**

A public package sidesteps all of that: nothing to expire, nothing to keep in sync.
The cost is that the image layers *are* the application source, so a public package
publishes the code even though the repository stays private. Nothing secret is baked in —
every credential arrives as a runtime environment variable.

If you fork this and want a private image instead, either add a `read:packages` token as a
registry credential **in the TrueNAS Apps UI** (not with `docker login`), or build on the
NAS and skip the registry:

```sh
git clone https://github.com/Cloudhunter77/mazsola_enterprise.git /mnt/tank/apps/leltar/src
cd /mnt/tank/apps/leltar/src/leltar && docker build -t leltar:local .
```

Then set the app's `image:` to `leltar:local` and add `pull_policy: never` beside it.

## 4. Install

**Apps → Discover Apps → ⋮ → Install via YAML.** Name it `leltar`, paste
`deploy/docker-compose.yaml`, and before saving:

- replace both `/mnt/tank/...` paths with your pool name,
- replace every `CHANGE_ME_*` value,
- use the **same** database password in `POSTGRES_PASSWORD` and in `DATABASE_URL`.

Save. The first start pulls the image, applies the schema migrations and seeds the category
list and a starter set of rooms — a minute or two. The app is then at `http://<nas>:8089`.

(Port 8089 because the receipt scanner already answers on 8088. If you run only this one,
any free port will do.)

Check it came up:

```sh
curl http://<nas>:8089/health
# {"status":"ok","database":true,"identifier":"claude","model":"claude-sonnet-5","worker":true}
```

## 5. On your phone

Open `http://<nas>:8089` over your VPN and add it to the home screen (iOS: Share → Add to
Home Screen; Android: menu → Install app). It then opens full-screen.

The working order is: **pick the room first**, then photograph. The app remembers the room
between uploads, because cataloguing one is a dozen photographs in a row and re-picking it
each time is the one thing guaranteed to make you stop.

Point the camera at a whole shelf rather than one object at a time — a photo of eight
things costs the same to read as a photo of one, and the app names all eight. Then
**Ellenőrzés**: for each suggestion, accept it, tap one of the alternatives, or retype it,
and **Mind rendben** when the photograph is done.

### iOS Shortcut (optional)

For a one-tap capture from the lock screen or Action Button:

1. Shortcuts → **+** → Add Action → **Take Photo**.
2. Add Action → **Get Contents of URL**:
   - URL: `http://<nas>:8089/api/photos?source=shortcut`
   - Method: **POST**
   - Headers: `X-API-Key` = the `API_KEY` you generated
   - Request Body: **Form**, one field named `file` of type *File*, value **Photo**
3. Name it "Leltár", and add it to the Home Screen or Action Button.

The upload returns immediately; the reading happens on the NAS. Open the app later to
approve the names. A shortcut cannot ask which room you are in, so those photographs
arrive without a place — set it on the review screen, or add `&place_id=<id>` to the URL
for a shortcut that always means one room.

## 6. Backups

Copy `scripts/backup.sh` to `/mnt/tank/apps/leltar/`, then **System → Advanced → Cron
Jobs**, daily as root:

```sh
sh /mnt/tank/apps/leltar/backup.sh
```

It writes a compressed `pg_dump` into the `backups` dataset and keeps the last 14. Check
the container name first (`docker ps | grep leltar`) and set `DB_CONTAINER` if it is not
`leltar-db-1`.

The photographs are not in the dump — they are files in the `photos` dataset, covered by
the ZFS snapshot. Both are needed for a full restore.

## 7. Updating

**Apps → leltar → Stop, then Start.** That is the whole procedure. The compose file sets
`pull_policy: always` on the app, so every start fetches the current `:latest`.

Then open **Statisztika → Rendszer és költség** in the app: the commit shown there should
match the latest one in the repository, and the schema line should say *naprakész*.
Migrations run at startup and the app serves nothing until they succeed, so if that page
loads, they applied.

**There is no "Pull image" button for a custom YAML app.** The three-dot menu's *Update*
is for catalog apps and does nothing here; `pull_policy: always` is what replaces it. If
you would rather not have every start reach out to GHCR, remove that line and pin an exact
tag instead — CI publishes `sha-<short commit>` beside `latest`.

Updating this app never touches the receipt scanner, and vice versa: separate images,
separate databases, separate CI workflows.

## Troubleshooting

**"SECRET_KEY is still a placeholder from the repository".** The app refuses to start
rather than run with a signing key published in this repository — anyone who could reach
it would be able to forge a login session. Generate one with `openssl rand -hex 32`. The
same guard rejects any key under 32 characters.

**The app container restarts in a loop.** Almost always the database: check that
`DATABASE_URL`'s password matches `POSTGRES_PASSWORD`, and that `pgdata` is owned by
568:568. `docker logs leltar-app-1` says which.

**Postgres will not initialise.** It refuses a non-empty data directory. The compose file
sets `PGDATA` one level down inside the mount for exactly this reason — keep that line.

**Photographs stay "Sorban áll" forever.** The worker is not running or has no key. Check
`/health` shows `"worker": true`, and look for `ANTHROPIC_API_KEY is not set` in the logs.
Nothing is lost — fix the key and press **Újraolvasás**.

**Every name comes back as "szék", "doboz", "eszköz".** The photograph is probably too far
back or too dark; the model names what it can actually resolve. Entries like that are
flagged `generic_name` and are worth retaking rather than retyping.

**Brands keep disappearing from the entries.** That is the app working as intended: a
brand is kept only when the model reports the text was legible in the frame, and a guess
from the shape of the object is dropped with `unverifiable_brand` shown against the entry.
If you want the brand recorded, photograph the label.

**It lists the radiator and the kitchen worktop.** Report it as a prompt bug — the
instruction in `leltar/extraction/prompt.py` is explicit about fixtures. Rejecting the
entry with **Nem kell** keeps it out of the inventory meanwhile.

**Identification costs more than expected.** Look at **Rendszer → Felismerési költség**:
cost is tokens × rate, and the photograph is most of the input. `MAX_IMAGE_EDGE=1024`
roughly halves it; `IDENTIFIER_MODEL=claude-haiku-4-5` costs about a fifth of Sonnet. The
per-confirmed-item figure on that page is the one that matters — photographing a whole
shelf at once is what makes it small.
