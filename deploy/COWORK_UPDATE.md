# Handover prompt for updating a running install

For a NAS that already has Receipt Tracker installed and working. If you are installing it
for the first time, use `COWORK_PROMPT.md` instead.

Paste everything below the line into Claude Cowork (or any new Claude session with shell
access to the NAS). It is written to be understood cold.

---

I already run a self-hosted app called **Receipt Tracker** on my TrueNAS SCALE NAS. It is
installed, healthy, and I photograph every receipt I get with it.

I want three things from this session:

1. **Deploy the new version** and check that what is new actually works.
2. **Fix the automatic update properly.** Stop/Start is supposed to pull the new image and
   it does not. I do not want a workaround this time — I want the cause found and fixed, so
   that the next update is Stop/Start and nothing else. Step 1 has what I know so far.
3. **Export every receipt I have not confirmed**, and give me the result. I have been
   leaving the misread ones unconfirmed on purpose so they can be studied; Step 5 is how to
   get them out and what format I need them in.

I will be at the keyboard the whole time. Stop and tell me if anything does not match what
is described here.

## What it is

Photograph a Hungarian till receipt on my phone; the app reads the shop, date, line items,
ÁFA rates and total with a vision model, checks the arithmetic balances, and stores it in
PostgreSQL. It then shows spending statistics, per-product price history, and which shop is
cheapest for my usual basket.

- Repository: `https://github.com/Cloudhunter77/mazsola_enterprise` (private)
- Branch: `claude/receipt-expense-tracker-mux58h`
- Image: `ghcr.io/cloudhunter77/receipt-tracker:latest` on GHCR — see Step 1 for how the
  NAS is authorised to pull it, which is not what you would assume
- TrueNAS app name: `receipt-tracker`, containers `receipt-tracker-app-1` and
  `receipt-tracker-db-1`, web UI on port 8088, reachable over my VPN only
- Deployment guide in the repo: `deploy/README.md`
- The web UI is in Hungarian.

## Ground rules

Each of these has already cost me time:

1. **The database is the app.** Every receipt I own is in it and there is no other copy of
   any of it. Nothing in this update is allowed to risk it: no dropping, no recreating, no
   reinstalling the app, no deleting the `pgdata` dataset, no `docker volume` anything. If
   you ever find yourself about to suggest a fresh install, stop and tell me instead.
   Step 0 takes a backup before anything else, and it is not optional.
2. **Give me one command at a time.** My shell is zsh over the TrueNAS web console. A
   multi-line block pasted at once gets its newlines collapsed and the commands run into
   each other. One command, I run it, I paste you the output.
3. **Never put a secret on a command line, and never print one back to me.** If I paste a
   secret into the chat by mistake, tell me immediately to revoke it.
4. **I am `truenas_admin`, not root.** Anything touching Docker needs `sudo -i` first.
5. **Prefer the TrueNAS web UI for anything TrueNAS owns** (datasets, apps, cron).
6. **Do NOT run `chown -R 568:568` over the app directory.** This already broke my
   database once. That command is in the *install* guide and applies only to a fresh, empty
   dataset. PostgreSQL sets its own internal ownership inside `pgdata`, and recursively
   chowning it caused `InsufficientPrivilegeError` on `pg_filenode.map`. Nothing in this
   update needs a permission change. (If it happens anyway: restart the `db` container,
   whose entrypoint re-asserts ownership as root, then restart `app`.)
7. **Verify each step before moving on**, and tell me what you expect so I can say if it
   differs.

## What is new in this version

- **Automatic product recognition.** Every till spells things differently — `PEPSI 1,5L`,
  `Pepsi Cola 1.5 l`, `PEPSI COLA 1500ML` — and until now each one was a separate line I had
  to map by hand. The app now groups them and gives each group a confidence: **green** means
  the names normalise identically and it links them itself, **yellow** means very close but
  worth a look, **red** is only a starting point. Different package sizes are always kept
  apart: 1,5 l and 0,5 l are different products.
- **It reaches backwards.** Mapping a product now also fills in the receipts *already* in
  the database, not just the ones I scan afterwards, and there is a button and an hourly
  pass that link old lines to products they letter-for-letter match.
- **The "failed to fetch" bug is fixed.** Staying on the first tab while a receipt finished
  processing showed an error even though it had worked. The page now retries a dropped
  request instead of giving up on the first one, and keeps polling when the phone screen
  comes back on.
- **A phone-friendly layout** — bigger tap targets, taller tab bar, no zoom-on-focus in
  form fields, and rows that stack instead of squeezing on a narrow screen.
- **A jump-to-latest-receipt button** on the capture screen.
- **Database migrations**, which run automatically at startup.

## Step 0 — Back up the database, before touching anything

Not because this update is risky — it adds one nullable column and an index, and there is a
test in the repo that seeds a database, runs the upgrade over it and checks every row is
still there. Because I have no other copy of my receipts, and a backup I have is worth more
than a promise that I will not need one.

As root (`sudo -i` first), one command:

```
docker exec receipt-tracker-db-1 pg_dump -U receipts -d receipts --clean --if-exists | gzip -9 > /mnt/tank/apps/receipt-tracker/backup-before-update.sql.gz
```

Adjust the pool name if mine is not `tank` — ask me rather than guessing. No password goes
on that line: `pg_dump` runs inside the container over the local socket.

Then check the file is not empty and looks like a dump:

```
ls -lh /mnt/tank/apps/receipt-tracker/backup-before-update.sql.gz
```

A few hundred KB or more is normal; a few hundred *bytes* means it failed and we stop there.

If I do not already have the nightly backup running, remind me at the end —
`scripts/backup.sh` in the repo is meant to be a TrueNAS cron job.

## Step 1 — Update the image

**Apps → receipt-tracker → Stop.** Wait until it actually reads *Stopped*, then **Start.**

That is the whole update *when the pull works*: the compose file carries `pull_policy: always`
on the `app` service, so every start fetches the current `:latest`. The first start after a
pull applies any outstanding migrations, which takes a moment.

**Do not look for a "Pull image" button — there isn't one** for an app installed from YAML.
The three-dot menu shows *Update* and *Convert to custom app*; *Update* is for catalog apps
and does nothing here.

### When Stop/Start does not actually update anything

**This is the part I most want fixed.** It has failed on me twice and both times the answer
was "try again", which is not an answer. Work through the list below in order, show me each
output, and keep going until either the app is running the new commit *because a pull
happened*, or you can tell me exactly which step fails and why. A manual `docker pull` that
gets me onto the new version is a diagnosis, not a fix — if that is where we end up, say so
plainly and tell me what would have to change for Stop/Start to do it by itself.

**1. Is `pull_policy` on the right service?** Open **Apps → receipt-tracker → Edit**. TrueNAS
re-sorts the YAML keys alphabetically when it saves, which pulls the two `image:` lines far
apart and makes it very easy to have added the line to `db` instead of `app` — I have done
exactly that. `pull_policy: always` must sit in the same indented block as
`image: ghcr.io/cloudhunter77/receipt-tracker:latest`, **not** the one with
`image: postgres:17-alpine`. If it is in the wrong place, move it and save; saving redeploys,
which is also the update.

**2. Read the deploy log.** As root:

```
tail -n 5 /var/log/app_lifecycle.log
```

That file is where TrueNAS records what happened when the app started, and it is the only
place the real reason shows up. What to look for:

- **`unauthorized`, `denied`, or a 401 on a manifest request** → this is the known one,
  and the cause is **not** the OS-level `docker login`. TrueNAS keeps registry
  credentials in two separate places:

  * `docker login` at the shell writes `/root/.docker/config.json`, which is what a
    manual `docker pull` reads;
  * the **Apps subsystem has its own registry credential store**, which is what an app
    deploy reads. It does not look at the file above.

  So `docker login` succeeding, and `docker pull` succeeding by hand, tell you nothing
  about whether the app can start — and chasing that appearance is how this went
  unsolved twice. **Test by starting the app, never by pulling at the shell.**

  The fix is whichever I have chosen; ask me which before doing either:
  *(a)* the GHCR package is public, in which case no credential is needed at all and a
  failure here means something else; or *(b)* an entry for `ghcr.io` exists in the
  **Apps** credential store. If it is (b) and the entry is missing or stale, tell me — I
  have to type the token into the TrueNAS UI myself. Never ask me to paste a token to
  you, and never put one on a command line.

- **No mention of a pull at all** → the policy is not being honoured. A manual
  `docker pull` here is a *diagnostic only*, and a misleading one: it exercises the OS
  credential path, not the one the app deploy uses, so it can succeed while the deploy
  still cannot pull. If it says `Image is up to date` while the Rendszer page shows an
  old commit, check the repository's Actions tab — the image may never have been
  published — before blaming the NAS.
- **`no space left on device`** → the pool is full; stop and tell me.

**3. Last resort: pin the exact build.** CI publishes `sha-<short commit>` alongside
`latest`. Changing the tag in the YAML to the exact one always forces a pull, because it is
an image the NAS has never seen. Tell me the tag you want to use and I will confirm it
against the repository first.

Whatever we end up doing, none of it touches `pgdata` — the database container is not being
replaced and my receipts are not involved in any of it.

## Step 2 — Confirm the update took, and that nothing was lost

Open `http://<nas-ip>:8088` over my VPN, then **Tábla → ⚙** (the Rendszer page).

- The **commit** should match the latest one in the repository — it is a link, so open it
  and check the message is the newest.
- The schema line should read **naprakész**.
- **Feldolgozó** should say it is running.

Then, and this matters more than the version number:

- **Blokkok** still lists my receipts, and the count is what it was before.
- Opening one still shows its photo.
- **Statisztika** still shows my months, not an empty chart.

If anything there is empty or a photo 404s, **stop immediately** and tell me — we have the
Step 0 backup and I would rather restore than keep going.

## Step 3 — The product recognition

This is the main new thing. Open **Árak**; the "Termékek felismerése" card is at the top.

1. Tell me how many unmapped lines it found, and roughly how many groups.
2. Press **Régiek összekapcsolása**. That pass links only lines that normalise
   letter-for-letter to a product I have already mapped — it fills in blanks and never
   overwrites anything. Tell me how many it linked.
3. Look at the groups themselves and tell me whether the colours make sense:
   - Does anything **green** group two things that are actually different products? That is
     the one failure that would matter, because green links itself.
   - Do the **yellow** ones look like genuine "same thing, different spelling" pairs?
   - Are two sizes of the same drink ever in one group? They must never be.
4. Confirm a couple of the obvious yellow ones with **Összekapcsolás** and check that the
   count of unmapped lines drops, and that the product then appears under **Árak** with its
   price history — including purchases from *before* I mapped it. That backfill is the point
   of the feature; if the history starts today, something is wrong and I want to know.

## Step 4 — The phone

Do this on my phone, not the desktop browser.

- Upload a receipt and **stay on the Rögzítés tab** until it finishes. It must not say
  *failed to fetch* — that was the bug. If it does, tell me the exact wording, because the
  new code puts a Hungarian message there instead of the browser's.
- Lock the phone mid-processing and unlock it. The result should still arrive.
- Check the tab bar and the buttons are comfortable to hit one-handed.
- Tapping a text field must not zoom the page in.
- The **latest receipt** button on the capture screen should jump straight to the last one.

## Step 5 — Export the receipts I never confirmed

This is the part I care about beyond the update itself.

A receipt I left **unconfirmed** is one whose reading was wrong. I have been leaving them
that way deliberately rather than correcting and confirming them, so that the mistakes are
still on file with their photographs. That pile is the raw material for improving the
extraction prompt, and I want it out of the NAS and into a form I can hand to the session
that writes the prompt.

There is a script in the image for exactly this. As root:

```
docker exec receipt-tracker-app-1 python scripts/export_unconfirmed.py
```

It reads only — it writes nothing to the database. It produces, in `/data/export` inside the
container, which is `/mnt/tank/apps/receipt-tracker/images/export` on the NAS (adjust the
pool name if mine is not `tank`, and ask me rather than guessing):

- `unconfirmed.md` — one section per receipt: status, review reasons, the header fields, a
  table of every line in printed order, and the model's own raw JSON response.
- `images/` — the photographs, each named after the same short id the Markdown uses.

Then:

1. Tell me how many receipts it exported.
2. **Paste the entire contents of `unconfirmed.md` to me in the chat**, as text. Not a
   summary, not the highlights — the whole file, including the raw JSON blocks. If it is too
   long for one message, split it across several and say which receipts are in each. The
   exact numbers are the evidence; a paraphrase is useless.
3. Tell me the filenames in `images/` and where the folder is on the NAS, so I can attach
   the photographs myself. Do not describe what is in the photographs — I need the pictures,
   not your reading of them, because comparing your reading against the model's would just
   be a third opinion.
4. If any receipt in the export is one I have since fixed by hand, say which — a correction
   I made is itself evidence of what went wrong.

If the script is not in the image, the update did not take; go back to Step 1. If it errors,
paste the whole traceback.

## Finally

Tell me plainly:

- whether the backup was taken, and where it is;
- whether the update went through, and if it did not, what
  `tail -n 5 /var/log/app_lifecycle.log` actually said;
- that my receipt count and images survived;
- what the product recognition found, and whether any green group was wrong;
- how many unconfirmed receipts were exported, with `unconfirmed.md` pasted in full;
- and anything that did not work, with the exact error rather than a summary.

If something needs a code change rather than configuration, say so rather than working
around it — I have a session that can make it.
