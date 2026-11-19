# Receipt Tracker (mazsola_enterprise) – overview

**Status:** active · **Last updated:** 2026-11-19

## Goal
A self-hosted app (TrueNAS SCALE) that turns photographed Hungarian receipts into a queryable
expense database, and since November 2026 also runs the household budget that used to live in a
Google Sheet: monthly plan, meeting-to-meeting periods, income, Revolut pockets, goals and the
wishlist. Two users: Balázs and Petra. See `README.md` for the app itself and
`docs/budgeting-plan.md` for the budgeting design.

## Current state
- Branch `claude/receipt-expense-tracker-mux58h` (the repo's default) is what CI builds into
  `ghcr.io/cloudhunter77/receipt-tracker:latest`; the NAS pulls that image. Every GitHub Action
  in the workflow is on its Node 24 major (2026-11-19).
- **Budgeting stage 1** (`7e394d5`): periods from one monthly meeting to the next, Terv (plan
  grid, amounts carry forward), Hónap (plan vs actual per line, per owner), Rendszeres (bills
  and income; variable bills and salaries are confirmed by hand), Havi megbeszélés (5 steps),
  the "no meeting yet" banner, the Pénz tab, settings behind ⚙.
- **Budgeting stage 2** (`a476ce4`, `0f928dd`): Revolut pockets with earmarks (goals with
  suggested monthly amounts, pocket lines like Hobbi, a wishlist pot), "Zsebből" on receipts,
  the meeting's transfer checklist and Revolut balance check, Kívánságlista under Lista.
- **Statisztika** (`e1b08e0`): tapping a category or shop bar lists what makes it up.
- 689 tests pass locally and in CI.
- **On the NAS** since 2026-11-19, budgeting migrations applied. No real budgeting data entered
  yet (#2, #5, #7).
- Decisions D1–D35 are in `DECISIONS.md` (D23–D35 are stage 2).

## Next steps
1. Find and fix the 19 million Ft Barkács entry with the Statisztika drill-down (#9).
2. Enter the real data: salaries and bills, Terv lines, pockets, goals, wishlist (#2, #5, #7),
   then hold the first Havi megbeszélés.
3. Stage 3, bank statement import (CSV), once it is known which banks besides Revolut (#4).

## Local development (this laptop)
- No system PostgreSQL, Docker or Node. Python deps and `pgserver` (a bundled PostgreSQL) live
  in the project `.venv`; Node 22 is in `~/.local/share/node/bin` (not on PATH).
- Tests need `TEST_DATABASE_URL` pointing at a PostgreSQL; start one from
  `.venv/lib/python3.12/site-packages/pgserver/pginstall/bin` on TCP only.
