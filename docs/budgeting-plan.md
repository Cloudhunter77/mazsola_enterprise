# Plan: budgeting in the app ("Pénz")

**Status:** stage 1 (the planning core) is built, tested and not yet deployed
(2026-11-06). Stages 2 and 3 are still plans. The plan was agreed in the claude.ai/code session
`session_015xmbBxtqJyQqJEscyjETrG` and saved here on 2026-11-06. Where building stage 1 made
a decision the plan left open, it is recorded as D15–D22 in `DECISIONS.md`.

**Source:** the household budget spreadsheet
(<https://docs.google.com/spreadsheets/d/16NCMcIrjgakptXtrS2af9cOlAoEy4ERHA_uF9YuBxyo/edit?gid=640898586>).
It is retired once the app can do this. It is not synced. Only its categories, the two goal
names and the six wishlist items get imported.

The decisions behind this plan are D1–D14 in [`DECISIONS.md`](../DECISIONS.md). Next steps are in
[`TODO.md`](../TODO.md).

## How it works

**Időszak (budget period).** A period starts at a monthly meeting and ends at the next one. It
is named after the month being planned at that meeting: a meeting on 2 Nov opens "November".
Receipts and income belong to a period by their date. From the 1st of each month, until that
month's meeting has happened, a banner says "Még nem volt havi megbeszélés".

**Terv (the plan).** A grid with budget lines down the side and the coming months across the
top. As in the sheet, an amount carries forward until you change it. Some rows fill themselves
in:

- recurring bills;
- yearly bills, spread out as a monthly amount;
- the suggested monthly amount for each goal.

The bottom row shows expected income minus everything planned, which is what's left free. It is
shown per person and for the household, and turns red when a month doesn't add up. That is the
"plan ahead" part.

**What counts as spending.** Each receipt line counts against its own category, so a
supermarket receipt with milk and washing-up liquid hits both lines. The split decides whose
lines it counts against (D5). A receipt linked to a goal still appears in Statisztika as real
spending. It doesn't count against the month's budget, because the goal paid for it (D9).

**Rendszeres (recurring items).** This is today's Előfizetések, extended to cover salaries as
well as bills. Each item has an owner, a payer and a default split. It is fixed or variable, and
monthly or yearly. Every period shows each item as either "várható" (expected) or
"megérkezett / kifizetve" (arrived / paid).

**Célok (goals).** Each goal has an owner, a target and a date. The app suggests how much to put
aside each month, records set-asides, and shows progress. When you buy the thing, you link the
receipt to the goal.

**Kívánságlista (wishlist).** Each item has an owner, a priority, an estimated price and a link.
Buying it links the receipt and records the real price. One tap moves an item to the shopping
list or turns it into a goal.

## The monthly meeting

A guided "Havi megbeszélés" screen replaces the sheet's 7-step checklist:

1. **Last period, still open:** unconfirmed salaries and bills, uncategorised receipts, and
   unsplit receipts that look shared.
2. **Plan vs actual:** by line, with the biggest overspends first.
3. **Settle up:** the Elszámolás balance, with Kiegyenlítés.
4. **Next period:** adjust the Terv column. Goal amounts are suggested.
5. **Close:** closes the old period and opens the new one from today.

## Screens

| Tab | Sub-pages |
|---|---|
| 📷 Rögzítés | Blokk · Árcímke · Kézzel (Kiadás / Bevétel) |
| 🛒 Lista | Bevásárlás · Kívánságlista (stage 2) |
| 🧾 Blokkok | Lista · Tábla · Elszámolás · Kategorizálás |
| 🏷️ Árak | Ártörténet · Polcárak |
| 💰 Pénz | Hónap · Terv · Rendszeres · Célok (stage 2) · Statisztika |
| ⚙ | Felhasználók · Javítani való · API költség · Rendszer |

**Hónap** shows the current period at a glance: income received vs expected; each line's plan,
actual and remaining amount; warnings; and the "Havi megbeszélés" button.

## What changes in the data

Every change adds to the database. Nothing existing is removed.

- **New tables:** budget periods; budget lines with planned amounts by month (the existing
  `budgets` table, unused so far, is extended into this); income entries; goals and goal
  transfers; wishlist items.
- **Recurring items** gain: income or expense, owner, payer, default split, and fixed or
  variable. Each monthly occurrence gets a status and an actual amount.
- **Receipts** gain an optional goal link.
- **New categories from the sheet:** Rezsi, Programok, Utazás, Hobbi, Váratlan kiadások. The
  sheet's Ajándékok uses the existing Ajándék category (D21).

## Stages

Each stage is usable on its own.

1. **Planning core:** periods and the monthly meeting, income, recurring items, budget lines,
   Hónap and Terv, and the new navigation. After this, the spreadsheet is no longer needed for
   planning.
2. **Goals and wishlist:** including linking a purchase to a goal, and importing the sheet's
   goals and wishlist.
3. **Bank statement import (CSV):** matched against receipts so nothing counts twice. Needs to
   know which banks.

## Settled questions

These were open when the plan was written. All five took the proposed default in brackets
(D15).

1. A receipt dated before the meeting but entered after it: does it go into the closed period or
   the current one? *(Its own period by date, flagged "zárás után rögzítve" for the next
   meeting.)*
2. Can a closed period be reopened to fix something? *(Yes, by either of you.)*
3. Does Statisztika switch to periods? *(No. Statisztika stays on calendar months, and Pénz uses
   periods.)*
4. Variable bills like rezsi: what amount should the plan expect? *(The last confirmed amount,
   until you change it.)*
5. Should the meeting banner also show on Rögzítés, where the app is opened most, or only under
   Pénz? *(Both.)*

The goals' targets and dates, and both incomes, are empty in the sheet, so they are entered in
the app once it supports them.
