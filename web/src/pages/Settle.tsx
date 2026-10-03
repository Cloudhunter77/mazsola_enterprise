/** Elszámolás: who owes whom, and the bills behind it.
 *
 *  The headline is one sentence in forints - "Petra 12 340 Ft-tal tartozik neked" - because
 *  that is the whole question. Below it, the shared bills that make it up, each a tap away
 *  from its receipt, and the settlements already made. Settling records that the money was
 *  handed over; it is a statement you make, not something the app can see happen, so it
 *  asks once before writing it down and can be taken back if it was a mistake.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api, type SplitSummary, type Transfer } from "../lib/api";
import { date, ft } from "../lib/format";
import { useSession } from "../lib/session";
import { AsyncBlock, Card, useAsync } from "../components/ui";

export default function Settle() {
  const [reload, setReload] = useState(0);
  const summary = useAsync(() => api.splitSummary(), [reload]);
  const users = useAsync(() => api.users(), []);
  const session = useSession();
  const me = session?.user_id ?? null;
  const refresh = () => setReload((n) => n + 1);

  const name = (id: string | null) =>
    id === me ? "Én" : users.data?.find((user) => user.id === id)?.display_name ?? "?";

  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Elszámolás</h1>

      <AsyncBlock state={summary}>
        {(data) => (
          <>
            <Card>
              {data.transfers.length === 0 ? (
                <p style={{ margin: 0, fontSize: "1.15rem", fontWeight: 650 }}>
                  ✓ Kvittek vagytok.
                </p>
              ) : (
                data.transfers.map((transfer) => (
                  <Debt key={`${transfer.from_user_id}-${transfer.to_user_id}`}
                        transfer={transfer} me={me} onSettled={refresh} />
                ))
              )}
              <p className="muted" style={{ fontSize: "0.82rem", marginBottom: 0 }}>
                Csak a megosztott blokkok számítanak bele. Egy blokkot a saját oldalán vagy
                rögtön a fotózás után oszthatsz meg.
              </p>
            </Card>

            <Card title="Megosztott blokkok" note={`${data.receipts.length} blokk`}>
              {data.receipts.length === 0 ? (
                <p className="muted" style={{ margin: 0 }}>Még nincs megosztott blokk.</p>
              ) : (
                <SharedBills data={data} name={name} />
              )}
            </Card>

            {data.settlements.length > 0 && (
              <Card title="Kiegyenlítések">
                {data.settlements.map((settlement) => (
                  <div key={settlement.id} className="row"
                       style={{ gap: 8, alignItems: "center", borderTop: "1px solid var(--grid)", paddingTop: 8, marginTop: 8 }}>
                    <span style={{ flex: 1 }}>
                      {date(settlement.settled_at)} · {name(settlement.from_user_id)} →{" "}
                      {name(settlement.to_user_id)}
                      {settlement.note && <span className="muted"> · {settlement.note}</span>}
                    </span>
                    <span className="num">{ft(settlement.amount)}</span>
                    <button
                      className="btn"
                      aria-label="Kiegyenlítés törlése"
                      onClick={async () => {
                        if (!window.confirm("Törlöd ezt a kiegyenlítést? A tartozás visszaáll.")) return;
                        await api.deleteSettlement(settlement.id);
                        refresh();
                      }}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </Card>
            )}
          </>
        )}
      </AsyncBlock>
    </>
  );
}

function Debt({ transfer, me, onSettled }: {
  transfer: Transfer;
  me: string | null;
  onSettled: () => void;
}) {
  const amount = Math.round(Number(transfer.amount));
  const [paying, setPaying] = useState<string>(String(amount));
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sentence =
    transfer.to_user_id === me
      ? `${transfer.from_name} ${ft(amount)}-tal tartozik neked.`
      : transfer.from_user_id === me
        ? `${ft(amount)}-tal tartozol ${transfer.to_name} felé.`
        : `${transfer.from_name} ${ft(amount)}-tal tartozik – ${transfer.to_name} kapja.`;

  async function settle() {
    const value = Number(paying.replace(/\s/g, "").replace(",", "."));
    if (!(value > 0)) {
      setError("Adj meg egy összeget.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.settle(transfer.from_user_id, transfer.to_user_id, value);
      setOpen(false);
      onSettled();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ marginBottom: 12 }}>
      <p style={{ margin: "0 0 10px", fontSize: "1.15rem", fontWeight: 650 }}>{sentence}</p>
      {open ? (
        <>
          <div className="field">
            <label>Mennyit adott át {transfer.from_user_id === me ? "te" : transfer.from_name}?</label>
            <input inputMode="decimal" value={paying} onChange={(event) => setPaying(event.target.value)} />
          </div>
          <div className="row" style={{ gap: 8 }}>
            <button className="btn primary" style={{ flex: 1 }} disabled={busy} onClick={settle}>
              Rögzítés
            </button>
            <button className="btn" style={{ flex: 1 }} disabled={busy} onClick={() => setOpen(false)}>
              Mégse
            </button>
          </div>
        </>
      ) : (
        <button className="btn block" onClick={() => setOpen(true)}>Kiegyenlítés…</button>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

function SharedBills({ data, name }: { data: SplitSummary; name: (id: string | null) => string }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Dátum</th>
            <th>Bolt</th>
            <th>Fizette</th>
            <th>Megosztás</th>
            <th className="num">Összeg</th>
          </tr>
        </thead>
        <tbody>
          {data.receipts.map((receipt) => (
            <tr key={receipt.receipt_id}>
              <td className="mono">
                <Link to={`/blokkok/${receipt.receipt_id}`}>{date(receipt.purchased_at)}</Link>
              </td>
              <td>{receipt.merchant_name ?? "–"}</td>
              <td>{name(receipt.paid_by_id)}</td>
              <td style={{ whiteSpace: "nowrap" }}>
                {receipt.shares
                  .map((share) => `${name(share.user_id)} ${Math.round(Number(share.percent))}%`)
                  .join(" · ")}
              </td>
              <td className="num">{ft(receipt.total_gross)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
