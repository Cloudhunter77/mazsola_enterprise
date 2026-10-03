/** Who paid this, and how it divides - on the receipt screen and right after a scan.
 *
 *  Two people is the case it is built for: a payer button each, and one slider between
 *  them where the middle is 50-50. Saving is immediate on a tap and a moment after the
 *  slider stops moving, so there is no Save button to forget. Underneath, it says what
 *  the choice means in forints - "Petra owes you 4 000 Ft for this" - because a percentage
 *  is the input, but the amount is what anyone actually wants to know.
 */

import { useEffect, useRef, useState } from "react";

import { api, type ReceiptDetail, type User } from "../lib/api";
import { ft } from "../lib/format";
import { useSession } from "../lib/session";
import { Card, useAsync } from "./ui";

type Splittable = Pick<ReceiptDetail, "id" | "total_gross" | "paid_by_id" | "shares">;

export default function SplitBill({ receipt, onSaved, bare = false }: {
  receipt: Splittable;
  onSaved: (detail: ReceiptDetail) => void;
  /** Without its own card, for places that are already inside one. */
  bare?: boolean;
}) {
  const session = useSession();
  const users = useAsync(() => api.users(), []);
  const me = session?.user_id ?? null;
  const people = (users.data ?? []).filter((user) => user.active);

  // Nothing to split with one person in the household, or before we know who you are.
  if (!me || people.length < 2) return null;
  const body = <Splitter receipt={receipt} onSaved={onSaved} me={me} people={people} />;
  return bare ? body : <Card title="Fizetés és megosztás">{body}</Card>;
}

function Splitter({ receipt, onSaved, me, people }: {
  receipt: Splittable;
  onSaved: (detail: ReceiptDetail) => void;
  me: string;
  people: User[];
}) {
  // The two ends of the slider: you, and whoever the bill is shared with. If it is shared
  // between two other people, show it as it is rather than inventing a side for you.
  const sharedWith = receipt.shares.map((share) => share.user_id);
  const left = sharedWith.length && !sharedWith.includes(me) ? sharedWith[0] : me;
  const [partner, setPartner] = useState(
    sharedWith.find((id) => id !== left) ?? people.find((user) => user.id !== left)!.id,
  );
  const payer = receipt.paid_by_id;

  // "Not split" is not a separate mode: it is the end of the slider where whoever paid
  // carries the whole bill, and the server stores exactly that as no split at all.
  const resting = () => {
    const share = receipt.shares.find((s) => s.user_id === partner);
    if (receipt.shares.length) return Number(share?.percent ?? 0);
    return payer === partner ? 100 : 0;
  };
  const [percent, setPercent] = useState(resting);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<number | null>(null);

  // Follow the receipt when it changes underneath - a new payer moves the resting end.
  useEffect(() => {
    if (pending.current === null) setPercent(resting());
  }, [receipt, partner]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => {
    if (pending.current) window.clearTimeout(pending.current);
  }, []);

  const name = (id: string | null) =>
    id === me ? "Én" : people.find((user) => user.id === id)?.display_name ?? "?";
  const total = Math.round(Number(receipt.total_gross ?? 0));
  const partnerAmount = Math.round((total * percent) / 100);
  const leftAmount = total - partnerAmount;

  async function save(paidBy: string, value: number) {
    setBusy(true);
    setError(null);
    try {
      onSaved(await api.splitReceipt(receipt.id, paidBy, [
        { user_id: left, percent: 100 - value },
        { user_id: partner, percent: value },
      ]));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // A receipt from before anyone recorded who paid gets you as the payer the moment you
  // split it - a split needs a payer, and you are the one dividing it up.
  const paidBy = payer ?? me;

  function slide(value: number) {
    setPercent(value);
    if (pending.current) window.clearTimeout(pending.current);
    // Saved once the slider has been still for a moment, not on every pixel of a drag.
    pending.current = window.setTimeout(() => {
      pending.current = null;
      save(paidBy, value);
    }, 450);
  }

  function jump(value: number) {
    if (pending.current) window.clearTimeout(pending.current);
    pending.current = null;
    setPercent(value);
    save(paidBy, value);
  }

  function choosePayer(id: string) {
    // Keep the division as it is; only who handed over the money changes. Unsplit stays
    // unsplit, on the new payer's end.
    const value = receipt.shares.length ? percent : id === partner ? 100 : 0;
    if (pending.current) window.clearTimeout(pending.current);
    pending.current = null;
    setPercent(value);
    save(id, value);
  }

  // What this bill means between the two of you, in money rather than percent.
  const debtor = paidBy === partner ? left : partner;
  const owedAmount = paidBy === partner ? leftAmount : partnerAmount;
  let verdict = "Nincs megosztva – az egészet ";
  if (owedAmount <= 0) {
    verdict += paidBy === me ? "te állod." : `${name(paidBy)} állja.`;
  } else if (debtor === me) {
    verdict = `Ezért a blokkért ${ft(owedAmount)}-tal tartozol – ${name(paidBy)} fizette.`;
  } else if (paidBy === me) {
    verdict = `${name(debtor)} ${ft(owedAmount)}-tal tartozik neked ezért a blokkért.`;
  } else {
    verdict = `${name(debtor)} ${ft(owedAmount)}-tal tartozik – ${name(paidBy)} fizette.`;
  }

  return (
    <div>
      <div className="muted" style={{ fontSize: "0.8rem", marginBottom: 6 }}>Ki fizetett?</div>
      <div className="row" style={{ gap: 8, marginBottom: 14 }}>
        {[left, partner].map((id) => (
          <button
            key={id}
            className="btn"
            style={{ flex: 1 }}
            aria-pressed={payer === id}
            disabled={busy}
            onClick={() => choosePayer(id)}
          >
            {name(id)}
          </button>
        ))}
      </div>

      {people.length > 2 && (
        <div className="field">
          <label>Kivel osztod meg?</label>
          <select value={partner} disabled={busy} onChange={(event) => setPartner(event.target.value)}>
            {people.filter((user) => user.id !== left).map((user) => (
              <option key={user.id} value={user.id}>{user.display_name}</option>
            ))}
          </select>
        </div>
      )}

      <div className="row" style={{ justifyContent: "space-between", fontSize: "0.9rem" }}>
        <span><strong>{name(left)}</strong> {100 - percent}% · {ft(leftAmount)}</span>
        <span><strong>{name(partner)}</strong> {percent}% · {ft(partnerAmount)}</span>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        step={5}
        value={percent}
        aria-label={`${name(partner)} része százalékban`}
        onChange={(event) => slide(Number(event.target.value))}
      />
      <div className="row" style={{ gap: 8 }}>
        <button className="btn" style={{ flex: 1 }} disabled={busy}
                aria-pressed={percent === 50} onClick={() => jump(50)}>
          50–50
        </button>
        <button className="btn" style={{ flex: 1 }} disabled={busy}
                aria-pressed={owedAmount <= 0}
                onClick={() => jump(paidBy === partner ? 100 : 0)}>
          Nincs megosztva
        </button>
      </div>

      <p style={{
        margin: "10px 0 0", fontSize: "0.9rem",
        color: owedAmount > 0 ? "var(--good-text)" : "var(--ink-muted)",
      }}>
        {verdict}
      </p>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
