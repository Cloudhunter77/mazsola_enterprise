# Handover prompt for a fresh install

For a NAS that does not have Leltár yet. Paste everything below the line into Claude
Cowork (or any new Claude session with shell access to the NAS) to have it carry out the
installation. It is written to be understood cold, with no memory of how the app was
built.

Two things in it are true only while the app lives on a feature branch, and both are
called out where they matter: the image tag is the branch's, not `latest`, and the GHCR
package may still be private.

---

I need you to install a self-hosted app called **Leltár** on my TrueNAS SCALE NAS. I will
be at the keyboard the whole time. Work through this step by step, and stop and tell me if
anything does not match what is described here.

## What the app is

A searchable database of the things in my house, with a picture of each one. I photograph a
shelf or a single object on my phone; a vision model names what it sees in Hungarian and
proposes an entry per object; I accept, tap an alternative, or retype. Every item gets its
own picture — cut out of the photograph at the box the model drew, so eight things
photographed together become eight entries with eight distinct pictures.

It is a catalogue, not a valuation: the model is never asked what anything is worth.

- Repository: `https://github.com/Cloudhunter77/mazsola_enterprise` (private)
- Branch: `claude/new-app-asaos5`
- App directory in the repo: `leltar/`
- Image: **`ghcr.io/cloudhunter77/leltar:claude-new-app-asaos5`** — see the note below
- Deployment guide in the repo: `leltar/deploy/README.md`
- Compose file to install: `leltar/deploy/docker-compose.yaml`
- Two containers: the app (FastAPI + web UI + identification worker) and PostgreSQL 17.
- The web UI is in Hungarian. Reachable over my VPN only; not exposed to the internet.

### About that image tag

The compose file in the repo says `ghcr.io/cloudhunter77/leltar:latest`. **That tag does
not exist yet.** CI publishes `latest` only from the repository's default branch, and this
app currently lives on `claude/new-app-asaos5`. What CI has actually published is:

- `ghcr.io/cloudhunter77/leltar:claude-new-app-asaos5` — rebuilt on every push to that
  branch, so it stays current
- `ghcr.io/cloudhunter77/leltar:sha-2c4910a` — that one exact build

Use the branch tag everywhere, including in the compose file (step 5 covers the edit). If
I later merge the branch into the default branch, `latest` starts being published and I can
switch the tag back.

### This NAS may already run the sister app

The same repository holds **Receipt Tracker**, which may already be installed here. The two
share nothing: different image, database, datasets, port and TrueNAS app name. Nothing in
this installation should touch it. If you find yourself editing anything under
`apps/receipt-tracker` or an app named `receipt-tracker`, stop — you are in the wrong one.

| | Receipt Tracker | Leltár |
|---|---|---|
| TrueNAS app name | `receipt-tracker` | `leltar` |
| Port | 8088 | **8089** |
| Datasets | `apps/receipt-tracker/…` | `apps/leltar/…` |

## What is already done

Do not redo these:

- CI is green: the tests pass, and the image was built, started and checked to serve
  `/health` before being published.
- The app code, the compose file and the deployment guide are all on the branch above.

## What is not done yet

- Making the image pullable by the NAS (step 0 — most likely blocker).
- Creating the datasets.
- Generating the secrets.
- Filling in and installing the compose file.
- Any verification that identification actually works.

## Ground rules

These exist because each one has already caused a problem here:

1. **Give me one command at a time.** My shell is zsh over the TrueNAS web console. A
   multi-line block pasted at once gets its newlines collapsed and the commands run into
   each other. One command, I run it, I paste you the output.
2. **Never put a secret on a command line, and never print one back to me.** If you need me
   to supply a key, tell me where to paste it into a prompt or a file. If I paste a secret
   into the chat by mistake, tell me immediately to revoke it.
3. **I am `truenas_admin`, not root.** Anything touching Docker needs `sudo -i` first.
4. **Prefer the TrueNAS web UI for anything TrueNAS owns** (datasets, apps, cron). The
   shell is fine for file permissions and Docker.
5. **Verify each step before moving to the next**, and tell me what you expect to see so I
   can tell you if it differs.

## Step 0 — Let the NAS pull the image

The repository is private, so the GHCR package it publishes starts private too. The sister
app's package was made public at some point; this one is new and probably has not been.

**Read this before testing anything, because it cost a day on the sister app.** TrueNAS
keeps registry credentials in *two* separate places and only one is used when an app
starts:

- `docker login` at the shell writes `/root/.docker/config.json`, which is what a manual
  `docker pull` reads.
- The **Apps subsystem keeps its own registry credentials**, and an app deploy reads only
  those.

So a successful `docker login` followed by a successful `docker pull` proves **nothing**
about whether the app will start. If the Apps store has no `ghcr.io` entry, every deploy
fails `unauthorized` while every check I run by hand succeeds — which looks exactly like a
flaky registry and is not one. **Test by starting the app, never by pulling at the shell.**

Pick one of these with me:

- **Make the package public** (what the sister app does, and what the compose file assumes).
  I do it in a browser at
  `https://github.com/users/Cloudhunter77/packages/container/leltar/settings` →
  *Danger Zone* → *Change visibility* → Public. Nothing secret is baked into the image —
  every credential arrives as a runtime environment variable — but be straight with me
  about the cost: the image layers *are* the application source, so a public package
  publishes the code even though the repository stays private.
- **Or add a credential to the Apps store**: a token from
  `https://github.com/settings/tokens` (classic) with only the **`read:packages`** scope,
  entered as a registry credential **in the TrueNAS Apps UI** — not with `docker login`.
  It expires, and when it does updates stop happening silently, so tell me to write the
  expiry date somewhere I will see it.

Ask me which I chose before continuing.

## Step 1 — Find the pool name

The compose file has placeholder paths of the form `/mnt/tank/...`. Ask me to run
`zpool list` and use my actual pool name everywhere from then on.

## Step 2 — Datasets

Have me create these through **Datasets → Add Dataset** in the web UI:

- `apps/leltar/photos` — the photographs, and the per-item pictures cut from them
- `apps/leltar/pgdata` — the PostgreSQL data directory
- `apps/leltar/backups` — optional, for nightly database dumps

Then, in a root shell, ownership must be uid/gid **568** (the TrueNAS `apps` user); the
containers run as that user and cannot write otherwise:

```
chown -R 568:568 /mnt/<pool>/apps/leltar
```

## Step 3 — Generate the secrets

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

The last one is my login password, hashed. It runs inside the image, so nothing needs
installing:

```
docker run --rm -it ghcr.io/cloudhunter77/leltar:claude-new-app-asaos5 python scripts/hash_password.py
```

It prompts twice, echoes nothing, and prints **two** forms of the hash. **Tell me to use
the compose-safe one** (the one where every `$` is doubled to `$$`). This matters: an
Argon2 hash contains five `$` characters, Docker Compose reads `$` as the start of a
variable substitution, and a raw hash pasted into the YAML is silently corrupted so that
every login fails with nothing in the logs to explain why.

I also need a key for the vision model. Ask me which I have:

- an **Anthropic** key from `console.anthropic.com` (`ANTHROPIC_API_KEY`) — the default,
  and what the prompt was written against. A Claude Pro or Max subscription does **not**
  cover it; the subscription and the API are billed separately.
- or an **OpenRouter** key from `openrouter.ai/keys` (`OPENROUTER_API_KEY`), which fronts
  Mistral, Qwen, Gemini and the rest. It needs a model id too, and there is deliberately no
  default because ids and prices change every few weeks. To see today's usable ones:
  `docker run --rm ghcr.io/cloudhunter77/leltar:claude-new-app-asaos5 python scripts/list_models.py`
  — it keeps only models that do vision **and** strict structured outputs, cheapest first.

## Step 4 — Smoke-test identification before installing anything

One real API call against a picture bundled in the image. No database, no containers,
nothing persistent. It is the cheapest way to find out whether my key and model work
together.

First, load the key into the shell without it touching the command line or shell history:

```
read -rs ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY
```

I paste the key at the silent prompt. Then:

```
docker run --rm -e ANTHROPIC_API_KEY ghcr.io/cloudhunter77/leltar:claude-new-app-asaos5 python scripts/try_identify.py tests/fixtures/shelf.jpg
```

Note `-e ANTHROPIC_API_KEY` with **no `=`** — that passes the variable through from my
shell. Writing `-e ANTHROPIC_API_KEY=<key>` would put the key on the command line.

(For OpenRouter instead: add `-e IDENTIFIER=openrouter -e OPENROUTER_API_KEY -e OPENROUTER_MODEL=<id>`
and load that key the same way.)

**What the fixture is:** a synthetic drawing of a shelf — a white mug, a stack of three
books, a wooden box with the word `SZERSZAM` printed on a label, a potted plant and a
table lamp. It is a drawing rather than a photograph, so do not judge the model's real
accuracy from it. What it does prove:

- it comes back with **Hungarian names** for several of those objects;
- it does **not** claim a brand — nothing brand-like is legible in the frame, and the app
  drops any brand the model says it could not read;
- the command prints the real **cost** of the call and, per object, whether a usable
  **box** was produced. A box is what becomes that item's picture.

Tell me what it found and what it cost. If it fails:

- *"ANTHROPIC_API_KEY is not set"* → the `read -rs` step did not take; redo it.
- *"Anthropic API error 401"* → wrong or revoked key.
- *"returned text rather than JSON"* (OpenRouter only) → that model ignores strict
  structured outputs. Pick another from `list_models.py`.
- *"Insufficient credits"* → I need to top up.

Do not proceed to the install until this passes.

## Step 5 — Fill in the compose file

Fetch `leltar/deploy/docker-compose.yaml` from the repo branch. Walk me through replacing:

- the image tag `:latest` → **`:claude-new-app-asaos5`** (see the note at the top — the
  `latest` tag does not exist yet)
- both `/mnt/tank/...` paths → my pool name
- `CHANGE_ME_DB_PASSWORD` → the 16-hex password, **in both places**: `POSTGRES_PASSWORD`
  and inside `DATABASE_URL`. They must match exactly or Postgres refuses every connection.
- `CHANGE_ME_API_KEY` → my Anthropic key (or, for OpenRouter, comment out the Anthropic
  lines, set `IDENTIFIER: openrouter`, and uncomment `OPENROUTER_API_KEY` and
  `OPENROUTER_MODEL`)
- `CHANGE_ME_SECRET` → the 32-hex value
- `CHANGE_ME_PASSWORD_HASH` → the **compose-safe** hash from step 3
- `CHANGE_ME_API_KEY_FOR_SHORTCUT` → the 24-hex value

Leave `PGDATA: /var/lib/postgresql/data/pgdata` exactly as it is. Postgres refuses to
initialise into a non-empty directory and a TrueNAS dataset is never empty, so the data
must live one level down inside the mount.

Leave the published port at **8089** unless I say otherwise — 8088 is the sister app's.

The app deliberately **refuses to start** if `SECRET_KEY` is still a placeholder or is
shorter than 32 characters; it would otherwise be signing my login cookie with a value
published in the repository. If you see that error, the key was not replaced properly.

## Step 6 — Install

**Apps → Discover Apps → ⋮ → Install via YAML.** Name it `leltar`, paste the filled-in
compose file, save.

The first start pulls the image, applies the schema migrations and seeds the category list
plus a starter set of rooms. Give it a couple of minutes. Then:

```
curl http://localhost:8089/health
```

Expected:

```
{"status":"ok","version":"...","commit":"...","database":true,"identifier":"claude","model":"claude-sonnet-5","worker":true}
```

`"worker": true` matters — without it photographs queue forever.

If the app container restarts in a loop, get the logs (`docker logs leltar-app-1`). The two
most likely causes are a database password mismatch between the two places it appears, and
`pgdata` not being owned by 568:568. If the *deploy* fails rather than the container, it is
step 0: the Apps subsystem cannot pull the image.

## Step 7 — First real things

1. Open `http://<nas-ip>:8089` in a browser on my VPN. Log in with the password I hashed.
2. **Helyek** — the seeded rooms are a guess at somebody's house. Have me rename them to
   my actual rooms (the name on each row is editable in place), delete the ones I do not
   have, and add anything worth naming inside one — a shelf, a box. **Áthelyezés** on a row
   moves it inside another place. Places nest, and asking for the garage later shows what
   is in the boxes in the garage. A place holding things will not delete; move or delete
   its contents first.
3. **Rögzítés** — pick the room first, then choose the mode. This is the part worth getting
   right, so explain both to me:
   - **Egy tárgy** — one object, deliberately. That frame becomes the item's picture and
     the model is told to name the subject rather than the table under it.
   - **Polc, szoba** — a whole shelf. A photo of eight things costs the same to read as a
     photo of one, and each object gets its own picture cut from the frame.
4. **Ellenőrzés** — for each suggestion I see the crop beside the name. Accept it, tap an
   alternative, or retype. **Mind rendben** finishes the photograph.
5. Have me do both modes on real things, then tell me what the model got wrong.

Things it is *supposed* to do, so do not report them as faults: dropping a brand it could
not actually read (shown as *"A márkát nem lehetett elolvasni a képen, ezért töröltük"*),
flagging a vague name like "doboz", and falling back to the whole photograph when it could
not place a box.

## Step 8 — Check the thing that makes it a database

In **Leltár**, have me search for something I just added, **typed without accents** —
`bogre` should find a *bögre*, `funyiro` a *fűnyíró*. Words can come in any order and each
one narrows. Then have me pick a room in the place filter and confirm it shows what is
inside places nested in it, not just what is loose in the room.

If that works, the catalogue is doing its job. Also check **Statisztika** → the *Képpel*
tile: it says what share of the catalogue has a picture, which is the number that decides
whether I can recognise a row without reading it.

## Step 9 — Once it works

- On my phone: open the site over the VPN and add it to the home screen, so it opens
  full-screen and the capture button goes straight to the camera.
- Optional nightly database backup — `leltar/scripts/backup.sh` plus a TrueNAS cron job,
  described in `leltar/deploy/README.md`. Note the photographs are **not** in the database
  dump: they are files in the `photos` dataset, so a full restore needs both, and one ZFS
  snapshot of `apps/leltar` covers them together.
- Optional iOS Shortcut for one-tap capture — recipe in `leltar/deploy/README.md`, using
  the `API_KEY` from step 3 as an `X-API-Key` header. A shortcut cannot ask which room I am
  in, so those photographs arrive without a place unless the URL carries one.

## Updating later

**Apps → leltar → Stop, then Start.** The compose file sets `pull_policy: always`, so every
start fetches the current build of whatever tag is set — and the branch tag is rebuilt on
every push, so this picks up new work without editing anything. Then open
**Statisztika → Rendszer és költség** and check the commit shown matches the latest one on
the branch, and that the schema line says *naprakész*.

## Finally

Tell me plainly what worked, what did not, and anything you had to change from these
instructions. In particular: if the names the model produces are poor on real photographs
of my things, say so — the instruction it follows lives in `leltar/extraction/prompt.py`
and can be tuned, and switching models is one environment variable.
