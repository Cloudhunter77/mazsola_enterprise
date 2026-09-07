# Handover prompt for updating a running install

For a NAS that already has Receipt Tracker installed and working. If you are installing it
for the first time, use `COWORK_PROMPT.md` instead.

Paste everything below the line into Claude Cowork (or any new Claude session with shell
access to the NAS). It is written to be understood cold.

---

I already run a self-hosted app called **Receipt Tracker** on my TrueNAS SCALE NAS. It is
installed, healthy, and reading real Hungarian receipts. A new version has been published
and I want you to update to it and check what is new actually works.

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
- The web UI is in Hungarian.

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
   database once. That command is in the *install* guide and applies only to a fresh, empty
   dataset. PostgreSQL sets its own internal ownership inside `pgdata`, and recursively
   chowning it caused `InsufficientPrivilegeError` on `pg_filenode.map`. Nothing in this
   update needs a permission change. (If it happens anyway: restart the `db` container,
   whose entrypoint re-asserts ownership as root, then restart `app`.)
6. **Verify each step before moving on**, and tell me what you expect so I can say if it
   differs.

## What is new in this version

- **A fix for dropped thousands separators.** The model was reading `8 999 Ft` as `999` and
  `-4 500` as `-500` — every amount containing a thousands space lost the group before it,
  while `929` came back fine. The prompt now drills that specific case, and the total is
  cross-checked against the model's own character-by-character transcription of it.
- **Kézi rögzítés** — type in a receipt you lost.
- **Előfizetések** — Spotify, YouTube and the like, charged automatically each month.
- **Tábla** — a new tab: one row per receipt (date, shop, amount), sortable, with CSV export.
- **A width floor on tall photos** (`MIN_IMAGE_WIDTH`, default 800), because capping the
  longest edge left a long receipt only ~500px wide.
- **A Rendszer page** (Tábla → ⚙) showing the running commit and the schema revision, so
  an update can be confirmed without a shell.
- **`pull_policy: always`** in the compose file, so Stop/Start updates the image.
- **Database migrations**, which run automatically at startup.

## Step 1 — Update the image

**Apps → receipt-tracker → Stop, then Start.**

That is it, if the app already carries `pull_policy: always` — every start then fetches the
current `:latest`. Check the compose file (**Apps → receipt-tracker → Edit**) for that line
under the `app` service. If it is missing, add it directly under the `image:` line and save;
saving redeploys, which is also the update.

**Do not look for a "Pull image" button — there isn't one** for an app installed from YAML.
The three-dot menu on the Application Info panel shows *Update* and *Convert to custom app*;
*Update* is for catalog apps and does nothing here.

The first start after the pull applies any outstanding migrations, which takes a moment.

## Step 2 — Confirm the update took, and that nothing was lost

Open `http://<nas-ip>:8088` over my VPN, then **Tábla → ⚙** (the Rendszer page).

- The **commit** should match the latest one in the repository — it is a link, so open it
  and check the message is the newest.
- The schema line should read **naprakész**.
- **Feldolgozó** should say it is running.

If the ⚙ button is not on the Tábla header at all, the new image did not load — the page
ships inside it.

Then check my existing receipts are still listed and that opening one still shows its photo.
If the list is empty or an image 404s, stop and tell me before doing anything else.

## Step 3 — Check the thousands-separator fix on the receipt that failed

I have a Rossmann receipt in the app that was read wrong, and **the right answer is known**,
which makes it the best test available.

The receipt prints:

```
CIKKSZ M:  67960 1 DB X 8 999 Ft
* POLICE TO BE EXOTI          8 999
ENGEDMÉNY                    -4 500
CIKKSZ M:  67960 1 DB X 8 999 Ft
* POLICE FREETODARE           8 999
ENGEDMÉNY                    -4 500
CIKKSZ M:  59028 1 DB X 929 Ft
VIGO SZ.ZSAK 60L               929
ÖSSZESEN:                    9 927 Ft
```

Previously it came back as 999, −500, 999, −500, 929 — total 1 927 instead of 9 927.

Find it under **Blokkok** (Rossmann, 9 927 Ft, probably flagged *Ellenőrzendő*) and press
**Újrafeldolgozás**. That re-runs extraction on the stored photo with the new prompt; it
costs one API call.

What I want to know:

- Are the two POLICE lines now **8 999** each and the two ENGEDMÉNY lines **−4 500**?
- Is the total **9 927** and does it say the arithmetic balances?
- If it is still wrong, tell me exactly which numbers came back — the pattern matters more
  than the fact it failed.

There is also a new review reason, *"A végösszeg számként és leírt formában nem egyezik"*.
That one means the model's number and its own transcription of the printed total disagree —
which is precisely this bug being caught rather than slipping through. Seeing it would be
the system working, not failing.

## Step 4 — The new Tábla tab

There should now be five tabs along the bottom: Rögzítés, Blokkok, **Tábla**, Statisztika,
Árak. Open Tábla and check:

- one row per receipt: date, shop, amount, and where it came from;
- clicking a column heading sorts by it, clicking again reverses;
- the shop filter box works;
- the **CSV** button downloads a file. Open it in Excel or LibreOffice and tell me whether
  the accented characters and the amounts come through correctly — it is
  semicolon-separated with a comma decimal, which is meant to open without an import
  dialogue on a Hungarian locale.

## Step 5 — Type in a lost receipt

**Tábla → + Kézi** (or the link at the bottom of the Rögzítés screen).

Enter something real that I have lost: shop, date, one or more lines. Note that the total
defaults to the sum of the lines, so a single line reading "Bevásárlás / 4 200" is a
complete entry when that is all I remember.

Check that it saves, lands as **Feldolgozva** (not in the review queue — I typed it, so
there is nothing to verify), and appears in Tábla and in Statisztika.

## Step 6 — Set up my subscriptions

**Tábla → Előfizetések → + Új előfizetés.** Add these two:

- **Spotify Premium** — I will tell you the amount and the day of the month.
- **YouTube Premium** — same.

Set the start date to the beginning of this year if I have been paying that long; a past
start date backfills every month that has come due since.

Then check the important property, because this runs automatically every hour forever and
must never charge twice:

1. Note the number in the **Eddig** column for Spotify.
2. Press **Futtatás most** twice.
3. That number must not change, and no new Spotify rows may appear in Tábla.

If it does change, stop and tell me immediately — that would be a real bug and I would
rather fix it than let it inflate a month.

Also worth confirming: the generated charges show up in **Statisztika** as ordinary
spending, not in some separate list.

## Step 7 — Optional, only if the numbers look tight

The width floor (`MIN_IMAGE_WIDTH`, default 800) makes long receipts cost more tokens —
roughly 2.5x on a very tall one, unchanged on an ordinary photo. Check **Felismerési
költség** after a few receipts and tell me the per-receipt figure and the token columns. If
it has jumped more than I like, the cheaper answer is to photograph long receipts in
sections (📷 További rész) rather than lowering the floor, because sections keep their full
width anyway.

## Finally

Tell me plainly:

- whether the update went through cleanly and my old receipts survived;
- what the Rossmann receipt read this time, number by number;
- whether the double-run test on Spotify held;
- and anything that did not work, with the exact error rather than a summary.

If something needs a code change rather than configuration, say so rather than working
around it — I have a session that can make it.
