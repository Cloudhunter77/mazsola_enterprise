/** Subscriptions: set once, charged every month by itself.
 *
 *  A rule here generates ordinary receipts, so Spotify shows up in the monthly total and the
 *  category breakdown exactly like a shop does. Deactivating stops future charges and keeps
 *  everything already generated - a cancelled subscription is still part of last year.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api, type Recurring as Rule } from "../lib/api";
import { ft, date as fmtDate } from "../lib/format";
import { AsyncBlock, Card, useAsync } from "../components/ui";

type Draft = {
  name: string; merchant_name: string; amount: string;
  cadence: string; day_of_month: string; starts_on: string; payment_method: string;
};

const today = () => new Date().toISOString().slice(0, 10);

const blank = (): Draft => ({
  name: "", merchant_name: "", amount: "",
  cadence: "monthly", day_of_month: String(new Date().getDate()),
  starts_on: today(), payment_method: "card",
});

const amountOf = (raw: string): number | null => {
  const cleaned = raw.replace(/\s| /g, "").replace(",", ".");
  const value = Number(cleaned);
  return cleaned && Number.isFinite(value) ? value : null;
};

export default function RecurringPage() {
  const [reload, setReload] = useState(0);
  const rules = useAsync(() => api.recurring(), [reload]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => setReload((n) => n + 1);

  async function save() {
    if (!draft) return;
    setError(null);
    const amount = amountOf(draft.amount);
    if (!draft.name.trim()) return setError("Adj nevet az előfizetésnek.");
    if (amount === null || amount <= 0) return setError("Az összegnek nullánál nagyobbnak kell lennie.");

    const body = {
      name: draft.name.trim(),
      // The shop name defaults to the subscription's own name: "Spotify" is both.
      merchant_name: (draft.merchant_name.trim() || draft.name.trim()),
      amount,
      cadence: draft.cadence,
      day_of_month: Number(draft.day_of_month) || 1,
      payment_method: draft.payment_method,
      starts_on: draft.starts_on,
      active: true,
    };

    setBusy(true);
    try {
      if (editing) await api.updateRecurring(editing, body);
      else await api.createRecurring(body);
      setDraft(null);
      setEditing(null);
      refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function toggle(rule: Rule) {
    await api.updateRecurring(rule.id, { ...rule, active: !rule.active });
    refresh();
  }

  async function remove(rule: Rule) {
    if (!confirm(`Töröljem a(z) "${rule.name}" szabályt? A már rögzített tételek megmaradnak.`)) {
      return;
    }
    await api.deleteRecurring(rule.id);
    refresh();
  }

  return (
    <>
      <div className="row page-actions" style={{ marginBottom: 14 }}>
        <h1 style={{ flex: 1 }}>Előfizetések</h1>
        <Link className="btn" to="/tabla">← Tábla</Link>
      </div>

      <Card>
        <p className="muted" style={{ marginTop: 0 }}>
          Ami minden hónapban lemegy, de sosem ad blokkot: Spotify, YouTube, edzőterem. Egyszer
          beállítod, utána magától bekerül – a statisztikába is.
        </p>
        {!draft && (
          <button className="btn primary" onClick={() => { setDraft(blank()); setEditing(null); }}>
            + Új előfizetés
          </button>
        )}
      </Card>

      {draft && (
        <Card title={editing ? "Szerkesztés" : "Új előfizetés"} action={
          <button className="btn" onClick={() => { setDraft(null); setEditing(null); }}>Mégse</button>
        }>
          <div className="grid cols-2" style={{ gap: 10 }}>
            <label>
              Név
              <input
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                placeholder="pl. Spotify Premium"
                autoFocus
              />
            </label>
            <label>
              Bolt / szolgáltató
              <input
                value={draft.merchant_name}
                onChange={(e) => setDraft({ ...draft, merchant_name: e.target.value })}
                placeholder="alapból a név"
              />
            </label>
            <label>
              Összeg (Ft)
              <input
                inputMode="decimal"
                value={draft.amount}
                onChange={(e) => setDraft({ ...draft, amount: e.target.value })}
                placeholder="1 999"
              />
            </label>
            <label>
              Gyakoriság
              <select
                value={draft.cadence}
                onChange={(e) => setDraft({ ...draft, cadence: e.target.value })}
              >
                <option value="monthly">Havonta</option>
                <option value="yearly">Évente</option>
              </select>
            </label>
            <label>
              Hányadikán
              <input
                type="number" min={1} max={31}
                value={draft.day_of_month}
                onChange={(e) => setDraft({ ...draft, day_of_month: e.target.value })}
              />
            </label>
            <label>
              Mikortól
              <input
                type="date"
                value={draft.starts_on}
                onChange={(e) => setDraft({ ...draft, starts_on: e.target.value })}
              />
            </label>
          </div>

          <p className="muted" style={{ fontSize: "0.84rem" }}>
            Rövidebb hónapban az utolsó napon terhel, nem marad ki. A múltbeli kezdődátum
            visszamenőleg is rögzíti az esedékes hónapokat.
          </p>

          {error && <p className="error">{error}</p>}
          <button className="btn primary" onClick={save} disabled={busy}>
            {busy ? "Mentés…" : "Mentés"}
          </button>
        </Card>
      )}

      <AsyncBlock state={rules} empty="Még nincs előfizetés rögzítve.">
        {(data) => (
          <Card
            title="Rögzített előfizetések"
            action={
              <button
                className="btn"
                onClick={async () => { await api.runRecurring(); refresh(); }}
                title="Az esedékes tételek rögzítése most, a következő automatikus kör előtt"
              >
                Futtatás most
              </button>
            }
          >
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Név</th>
                    <th className="num">Összeg</th>
                    <th>Mikor</th>
                    <th>Következő</th>
                    <th className="num">Eddig</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.map((rule) => (
                    <tr key={rule.id} style={{ opacity: rule.active ? 1 : 0.55 }}>
                      <td>
                        {rule.name}
                        {!rule.active && <span className="muted"> · szünetel</span>}
                        {rule.merchant_name !== rule.name && (
                          <div className="muted" style={{ fontSize: "0.8rem" }}>
                            {rule.merchant_name}
                          </div>
                        )}
                      </td>
                      <td className="num">{ft(rule.amount)}</td>
                      <td>
                        {rule.cadence === "yearly" ? "évente" : "havonta"} {rule.day_of_month}.
                      </td>
                      <td>{rule.next_charge ? fmtDate(rule.next_charge) : "–"}</td>
                      <td className="num">{rule.charge_count}</td>
                      <td className="num" style={{ whiteSpace: "nowrap" }}>
                        <button
                          className="btn"
                          onClick={() => {
                            setEditing(rule.id);
                            setDraft({
                              name: rule.name,
                              merchant_name: rule.merchant_name,
                              amount: String(rule.amount),
                              cadence: rule.cadence,
                              day_of_month: String(rule.day_of_month),
                              starts_on: rule.starts_on,
                              payment_method: rule.payment_method,
                            });
                          }}
                        >
                          ✎
                        </button>{" "}
                        <button className="btn" onClick={() => toggle(rule)}>
                          {rule.active ? "⏸" : "▶"}
                        </button>{" "}
                        <button className="btn" onClick={() => remove(rule)}>🗑</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </AsyncBlock>
    </>
  );
}
