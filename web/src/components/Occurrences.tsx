/** One month of each recurring bill and income: what is expected, and saying it happened.
 *
 *  A fixed bill books itself on its day, so all it offers is "Kihagyás" for a month it did
 *  not happen. A variable bill and every salary wait here with the expected amount already
 *  filled in - the last one, for a variable bill - so the usual case is a single tap, and
 *  the unusual one is correcting a number first.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api, type Occurrence, type Person } from "../lib/api";
import { amountOf, dayLabel, ownerName, plain } from "../lib/budget";
import { ft } from "../lib/format";

export default function Occurrences({ items, users, onChange }: {
  items: Occurrence[];
  users: Person[];
  onChange: () => void;
}) {
  return (
    <div>
      {items.map((item) => (
        <OccurrenceRow
          key={`${item.recurring_id}-${item.month}`}
          item={item}
          users={users}
          onChange={onChange}
        />
      ))}
    </div>
  );
}

function statusText(item: Occurrence): string {
  const income = item.direction === "income";
  const fixedBill = !income && item.amount_mode === "fixed";
  switch (item.status) {
    case "done":
      return `${income ? "megérkezett" : "kifizetve"}${item.booked_on ? ` · ${dayLabel(item.booked_on)}` : ""}`;
    case "skipped":
      return "kihagyva ebben a hónapban";
    case "due":
      if (fixedBill) return `esedékes ${dayLabel(item.due)} · hamarosan magától rögzül`;
      return income ? `esedékes ${dayLabel(item.due)} · megérkezett?` : `esedékes ${dayLabel(item.due)} · mennyi lett?`;
    default:
      return fixedBill ? `magától rögzül · ${dayLabel(item.due)}` : `várható · ${dayLabel(item.due)}`;
  }
}

function OccurrenceRow({ item, users, onChange }: {
  item: Occurrence; users: Person[]; onChange: () => void;
}) {
  const income = item.direction === "income";
  const fixedBill = !income && item.amount_mode === "fixed";
  const waiting = item.status === "expected" || item.status === "due";
  const [amount, setAmount] = useState(plain(item.expected_amount));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      onChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const confirm = () => run(async () => {
    const value = amountOf(amount);
    if (value === null || value <= 0) throw new Error("Adj meg egy összeget.");
    await api.confirmOccurrence(item.recurring_id, { month: item.month, amount: value });
  });

  return (
    <div className="occ-row">
      <div style={{ minWidth: 0, flex: "1 1 180px" }}>
        <div>
          {income ? "＋ " : ""}{item.name}
          <span className="muted small"> · {ownerName(users, item.owner_id)}</span>
        </div>
        <div className={`small ${item.status === "due" && !fixedBill ? "" : "muted"}`}
             style={item.status === "due" && !fixedBill ? { color: "var(--serious)" } : undefined}>
          {statusText(item)}
        </div>
        {error && <div className="error">{error}</div>}
      </div>

      <div className="occ-actions">
        {waiting && !fixedBill && (
          <>
            <input
              inputMode="decimal"
              aria-label={`${item.name} összege`}
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
            <button className="btn primary" disabled={busy} onClick={confirm}>
              {income ? "Megérkezett" : "Kifizetve"}
            </button>
          </>
        )}
        {waiting && fixedBill && <span className="mono">{ft(item.expected_amount)}</span>}
        {waiting && (
          <button
            className="btn" disabled={busy}
            title="Ebben a hónapban nem volt"
            onClick={() => run(() => api.skipOccurrence(item.recurring_id, item.month))}
          >
            Kihagyás
          </button>
        )}

        {item.status === "done" && (
          <>
            {item.receipt_id ? (
              <Link className="mono" to={`/blokkok/${item.receipt_id}`}>{ft(item.amount)}</Link>
            ) : (
              <span className="mono">{ft(item.amount)}</span>
            )}
            {!fixedBill && (
              <button
                className="btn" disabled={busy}
                onClick={() => run(() => api.undoOccurrence(item.recurring_id, item.month))}
              >
                Visszavonás
              </button>
            )}
          </>
        )}
        {item.status === "skipped" && (
          <button
            className="btn" disabled={busy}
            onClick={() => run(() => api.undoOccurrence(item.recurring_id, item.month))}
          >
            Visszavonás
          </button>
        )}
      </div>
    </div>
  );
}
