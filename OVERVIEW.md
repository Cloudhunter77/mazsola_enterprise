# Receipt Tracker (mazsola_enterprise) – overview

**Status:** active · **Last updated:** 2026-11-17

## Goal
A self-hosted app (TrueNAS SCALE) that turns photographed Hungarian receipts into a queryable
expense database, and since November 2026 also runs the household budget that used to live in a
Google Sheet: monthly plan, meeting-to-meeting periods, income, Revolut pockets, goals and the
wishlist. Two users: Balázs and Petra. See `README.md` for the app itself and
`docs/budgeting-plan.md` for the budgeting design.

## Current state
- Branch `claude/receipt-expense-tracker-mux58h` (the repo's default) is pushed up to `e1b08e0`.
  CI builds `ghcr.io/cloudhunter77/receipt-tracker:latest` from it; the NAS pulls that image.
- **Budgeting stage 1** (`7e394d5`): periods from one monthly meeting to the next, Terv (plan
  grid, amounts carry forward), Hónap (plan vs actual per line, per owner), Rendszeres (bills
  and income; variable bills and salaries are confirmed by hand), Havi megbeszélés (5 steps),
  the "no meeting yet" banner, the Pénz tab, settings behind ⚙.
- **Budgeting stage 2** (`a476ce4`, `0f928dd`): Revolut pockets with earmarks (goals with
  suggested monthly amounts, pocket lines like Hobbi, a wishlist pot), "Zsebből" on receipts,
  the meeting's transfer checklist and Revolut balance check, Kívánságlista under Lista.
- **Statisztika** (`e1b08e0`): tapping a category or shop bar lists what makes it up.
- 689 tests pass locally and in CI.
- **Not yet on the NAS**: the NAS still runs the version from before budgeting until it is
  pulled and restarted (#8). Both migrations run on start.
- Decisions D1–D35 are in `DECISIONS.md` (D23–D35 are stage 2).

## Next steps
1. Update the NAS and check ⚙ Rendszer (#8).
2. Find and fix the 19 million Ft Barkács entry with the new Statisztika drill-down (#9).
3. Enter the real data: salaries and bills, Terv lines, pockets, goals, wishlist (#2, #5, #7),
   then hold the first Havi megbeszélés.
4. Stage 3, bank statement import (CSV), once it is known which banks (#4).
5. CI housekeeping: GitHub Actions still on Node 20 (#10).

## Local development (this laptop)
- No system PostgreSQL, Docker or Node. Python deps and `pgserver` (a bundled PostgreSQL) live
  in the project `.venv`; Node 22 is in `~/.local/share/node/bin` (not on PATH).
- Tests need `TEST_DATABASE_URL` pointing at a PostgreSQL; start one from
  `.venv/lib/python3.12/site-packages/pgserver/pginstall/bin` on TCP only.
