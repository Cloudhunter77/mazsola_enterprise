# Log

## 2026-11-19 – Housekeeping
- The NAS is updated; both budgeting migrations ran.
- CI: every action moved to its Node 24 major (checkout, setup-node, setup-python v7;
  setup-buildx v4, login v4, metadata v6, build-push v7), after checking each new major's
  runtime, its inputs we use, and its breaking changes against this workflow.
- TODO tidied: finished items moved under Done, the stray "Receipt and expense tracker" item
  removed.

## 2026-11-17 – Budgeting stage 2, deploy, clickable Statisztika
- Grilled stage 2: goals and the wishlist became Revolut pockets with earmarks (D23–D35).
- Built pockets, goals, pocket lines, "Zsebből" on receipts, the meeting's transfer checklist
  and Revolut check, and Kívánságlista; fixed two ledger bugs found while clicking through.
- Checked stage 2 at phone width by measurement (Chrome's iframe screenshots time out here);
  tightened Pénz's five-item sub-navigation so it fits on a phone.
- Committed stage 1 (`7e394d5`) and stage 2 (`a476ce4`, `0f928dd`), pushed; CI green.
- Made Statisztika's category and shop bars clickable to trace a 19M Barkács entry (`e1b08e0`).
- Open: update the NAS (#8), find the Barkács line (#9), enter the real data (#2, #5, #7).

## 2026-11-06 – Budgeting stage 1
- Recovered the planning conversation from the cloud session and saved it as
  `docs/budgeting-plan.md`, with decisions D1–D22.
- Set up local testing on the laptop: project `.venv` with `pgserver`, Node 22 in
  `~/.local/share/node`.
- Built periods, Terv, Hónap, Rendszeres with income, the monthly meeting and the Pénz tab;
  clicked through it in Chrome at desktop and phone width.
