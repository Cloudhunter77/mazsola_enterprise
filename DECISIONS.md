# Decisions

Numbered, never rewritten. A later decision supersedes an earlier one by saying so.

D1–D14 were agreed while planning budgeting ("Pénz") in the claude.ai/code session
`session_015xmbBxtqJyQqJEscyjETrG`, and recorded here on 2026-11-06. The full plan is
[`docs/budgeting-plan.md`](docs/budgeting-plan.md).

## D1 — Retire the budget spreadsheet instead of syncing with it (2026-11-06)
The app takes over planning, and the spreadsheet is retired once the app can do this. There is no
two-way sync. Only its categories, the two goal names (Kanapé, Fényképezőgép) and its six wishlist
items get imported.

## D2 — Shared money is per-receipt splits only (2026-11-06)
There is no joint pot. Settling up stays in Elszámolás.

## D3 — Everything is visible to both of us (2026-11-06)

## D4 — Expenses without a receipt: manual entry and recurring items first (2026-11-06)
Manual entry and recurring items come now. Bank statement import comes later (stage 3).

## D5 — Budget lines belong to Közös, Balázs or Petra (2026-11-06)
A split receipt counts in full against the shared (Közös) lines. An unsplit one counts against
its payer's lines.

## D6 — One category tree, budget at any level (2026-11-06)
A parent's budget covers its children. Each line is tagged Fix / Változó / Célalap /
Megtakarítás.

## D7 — Income is an expected salary per person, confirmed when it arrives (2026-11-06)
Bonuses are added by hand.

## D8 — Recurring items are planned ahead (2026-11-06)
Fixed amounts are booked automatically. Variable ones wait for the actual amount to be entered.
Yearly ones are spread over 12 months in the plan.

## D9 — Goals are a virtual pot (2026-11-06)
Setting money aside for a goal is a transfer, not spending. A purchase linked to a goal draws
down the saved money instead of counting against that month's budget, because the goal paid for
it. It still shows as real spending in Statisztika.

## D10 — No carry-over (2026-11-06) (→ D25)
Unspent budget does not roll into the next month.

## D11 — The wishlist and the shopping list are two lists, linked (2026-11-06)
One tap moves a wishlist item to the shopping list or turns it into a goal.

## D12 — A budget period runs from one monthly meeting to the next (2026-11-06)
It does not follow the calendar month. It is named after the month planned at the meeting. From
the 1st of each month, until that month's meeting has happened, the app shows a warning banner.
Why: "we sit down each month to discuss the previous and next month finances, that should be the
start and end point." Since the meeting defines the period, whose salary arrives first doesn't
matter.

## D13 — The Statisztika tab becomes "Pénz" (2026-11-06)
The app keeps five tabs plus ⚙, and a few pages move to where they belong (see the plan's
Screens table). Why: five tabs fit a phone.

## D14 — Build budgeting in three stages, plan first (2026-11-06)
Stage 1 is the planning core, stage 2 goals and wishlist, stage 3 bank statement import. Each
stage is usable on its own. Nothing is implemented until the plan for a stage is agreed.

## D15 — The five open questions take their proposed defaults (2026-11-06)
1. A receipt dated before a meeting but entered after it belongs to its own (closed) period by
   date, and is flagged "zárás után rögzítve" for the next meeting.
2. Either of us can reopen a closed period.
3. Statisztika stays on calendar months; Pénz uses meeting-to-meeting periods.
4. A variable bill is planned at its last confirmed amount until changed.
5. The "no meeting yet" banner shows on both Rögzítés and Pénz.

Also: implementation of stage 1 starts now, without a separate stage-1 plan review (supersedes
the "plan agreed first" part of D14 for stage 1).

## D16 — A budget line covers one or more categories (2026-11-06)
A line has a name, an owner (Közös / a person), a tag (D6) and a set of categories; each
category brings its subcategories with it. A category can be in at most one active line per
owner. Why: the spreadsheet's lines don't map one-to-one onto the app's categories -
"Kaja – bevásárlás" is Élelmiszer and Ital together.

## D17 — A bill from Rendszeres counts against its own row, not a category line (2026-11-06)
Every recurring bill is its own row in Terv and Hónap, so a receipt it generated is matched to
that row and never also to the line of its category. Why: otherwise the same rent would be
planned twice (its row and the category line) and spent twice.

## D18 — What books itself (2026-11-06)
A fixed recurring bill is booked on its due day, as before. A variable bill and every income
wait to be confirmed with the actual amount ("Kifizetve" / "Megérkezett"), and either can be
marked "Kihagyva" for a month it didn't happen. Why: D7 and D8; a salary that has not arrived
must not show up as money you have.

## D19 — The per-person view splits shared plans equally (2026-11-06)
"Szabad" per person = own income − own lines − an equal share of the Közös lines. A Közös
recurring item uses its default split when it has one. Why: it matches the spreadsheet's
"Hozzájárulás módja: Egyenlő" (50-50). An income-proportional split can be added later.

## D20 — Spending is counted at what was actually paid (2026-11-06)
Discounts and cash rounding are spread over a receipt's lines in proportion, so the lines of a
receipt add up to its total. Yearly recurring items are planned at 1/12 per month and are not
flagged as overspent in the month they are paid.

## D21 — Categories from the sheet (2026-11-06)
New: Rezsi (top-level), Programok, Utazás and Hobbi (under Szabadidő), Váratlan kiadások (under
Egyéb). The sheet's "Ajándékok" uses the existing "Ajándék" category instead of a near-duplicate.
New categories now reach existing installs because the idempotent category seed runs at every
start (nothing in the app deletes or renames a category).

## D22 — Closing a period freezes its plan (2026-11-06)
Closing writes each line's amount for that month explicitly, and plan edits to a closed month
are refused until it is reopened. Why: amounts carry forward, so without the snapshot an edit to
an earlier month could silently change a month already discussed.

## D23 – A pot is a Revolut pocket: a pocket record (name, whose account, opening balance as of a date) added by hand; goals and pocket lines are earmarks inside it, several per pocket; money no earmark claims shows as 'nincs hozzárendelve' (2026-11-17)
**Why:** the household keeps savings, goals and hobby money in real Revolut pockets, and one pocket (Savings) holds several purposes

## D24 – Pockets have no currency: every amount is plain forints; a euro pocket like Savings is entered in its own numbers and read as euros by the user (2026-11-17)
**Why:** the user prefers simplicity; 40 vs 40 000 is too big a difference to misread

## D25 – A budget line can be 'zsebből' (pocket-funded): its monthly amount is a transfer into its pocket, its purchases draw the pocket down, and what is left carries over; Megtakarítás lines are always pocket lines (2026-11-17)
Replaces D10.
**Why:** money moved into a Revolut pocket stays there; no-carry-over still holds for everyday lines

## D26 – Goals are earmarks with target, date and progress; their Terv row is editable, carries forward, and shows 'javasolt: (target - saved) / months left'; a bought goal's leftover is moved to another earmark or released (2026-11-17)
**Why:** agreed in the stage 2 grilling (Q3, Q5)

## D27 – A pocket pays only up to its balance: anything beyond counts as normal spending in its category that month (2026-11-17)
**Why:** a pot going negative would hide overspending; agreed for goals and every pocket (Q4, Q18)

## D28 – Meeting step 5 lists the transfers to make (who sends what to whose pocket, Közös earmarks split equally); each is ticked by default, unticked ones stay in Hónap Teendők, and only ticked transfers count toward a pocket's balance; extra deposits/withdrawals by hand on Zsebek; the meeting asks for each pocket's actual Revolut balance and shows the difference (2026-11-17)
**Why:** pocket balances are real money, so they should only change when a transfer actually happened

## D29 – A receipt can be marked as paid from a pocket ('Zsebből' selector on the receipt page, also on Rendszeres, Kézzel and 'Megvettük, nincs blokk'); it is guessed from the categories when every line falls under one pocket line, shown as a guess, and a person's choice always wins; a pocket-paid receipt counts only against that pocket (2026-11-17)
**Why:** the user asked for a selector like the category picker; groceries on a trip belong to Kirándulás, not Kaja

## D30 – Purchases are linked to a goal or wishlist item per receipt line (all ticked by default), from the receipt page or from the goal/item ('Megvettük': pick a recent receipt, or 'nincs blokk' with price and date) (2026-11-17)
**Why:** a camera bought with an SD card should draw only the camera from the pot

## D31 – Wishlist: owner, name, priority (Alacsony / Alacsony-közepes / Közepes / Közép-magas / Magas), estimated price, link or shop, note, optional catalogue product; each owner may have a wishlist earmark that its purchases draw from; 'Listára' copies to the shopping list linked, and only linking the real purchase closes the item with its actual price (2026-11-17)
**Why:** matches the spreadsheet's five priorities and its monthly wishlist pot

## D32 – Pénz sub-pages: Hónap, Terv, Rendszeres, Zsebek, Statisztika (Zsebek replaces the planned Célok); Kívánságlista is under Lista (2026-11-17)
**Why:** goals are now earmarks inside pockets, so pockets are the page

## D33 – The spreadsheet's 2 goals and 6 wishlist items are entered by hand after deploying, not imported (2026-11-17)
**Why:** they have no amounts or dates yet, and eight entries are quicker to type than an import is to write

## D34 – A purchase on a pocket line (e.g. Hobbi) that exceeds that line's money uses the pocket's unassigned money next, and only then counts as the month's spending; a purchase linked to a goal draws only from the goal (2026-11-17)
**Why:** D27 says the pocket pays up to its balance: money already sitting in the Hobby pocket should pay for hobby things even before it is earmarked; a goal stays strict as agreed in Q4

## D35 – A Rendszeres item paid from a pocket has no plan row of its own and its bills draw from the pocket; its money is planned as that pocket's line (2026-11-17)
**Why:** planning it both as its own row and as the pocket's monthly transfer would count the same money twice
