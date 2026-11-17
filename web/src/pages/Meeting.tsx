/** Havi megbeszélés: the monthly meeting, in five steps.
 *
 *  It replaces the spreadsheet's seven-step checklist. Each step shows only what needs
 *  talking about, and everything it shows can be dealt with on the spot:
 *
 *  1. what the period being closed still has open - salaries nobody confirmed, bills without
 *     an amount, receipts without a category or that look shared but were not split;
 *  2. plan against actual, the biggest overspend first;
 *  3. who owes whom, settled right there;
 *  4. next month's amounts, with what is left free updating as you type;
 *  5. close: the running period ends and the next one starts today.
 *
 *  The very first time there is nothing to close, so it only starts the first period.
 */

import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, type BudgetStatus, type MonthView, type Plan, type ProposedTransfer } from "../lib/api";
import { amountOf, isAside, monthLabel, ownerName, periodRange, plain, pocketLabel } from "../lib/budget";
import { ft } from "../lib/format";
import { useSession } from "../lib/session";
import { AsyncBlock, Card, useAsync } from "../components/ui";
import { Issues } from "./Month";
import { Debt } from "./Settle";

const addMonths = (iso: string, count: number): string => {
  const [y, m] = iso.split("-").map(Number);
  const index = y * 12 + (m - 1) + count;
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}-01`;
};

export default function Meeting() {
  const status = useAsync(() => api.budgetStatus(), []);
  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Havi megbeszélés</h1>
      <AsyncBlock state={status}>
        {(data) => (data.current ? <FullMeeting status={data} /> : <FirstPeriod status={data} />)}
      </AsyncBlock>
    </>
  );
}

function FirstPeriod({ status }: { status: BudgetStatus }) {
  const navigate = useNavigate();
  const [startsOn, setStartsOn] = useState(status.suggested_starts_on);
  const [month, setMonth] = useState(status.suggested_month);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const thisMonth = status.today.slice(0, 8) + "01";
  const options = [addMonths(thisMonth, -1), thisMonth, addMonths(thisMonth, 1)];

  async function start() {
    setBusy(true);
    setError(null);
    try {
      await api.openPeriod({ starts_on: startsOn, month });
      navigate("/terv");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <Card title="Az első időszak">
      <p style={{ marginTop: 0 }}>
        Egy időszak az egyik havi megbeszéléstől a következőig tart, és arról a hónapról kapja
        a nevét, amit akkor terveztek. Ami ezalatt történik – blokk, bevétel – a dátuma szerint
        tartozik bele.
      </p>
      <p className="muted small">
        Indítás előtt érdemes felvenni a fizetéseket és a havi számlákat a{" "}
        <Link to="/rendszeres">Rendszeres</Link> alatt; a kereteket utána a Tervben adod meg.
      </p>
      <div className="grid cols-2" style={{ gap: 10 }}>
        <label>
          A megbeszélés napja
          <input type="date" value={startsOn} max={status.today}
                 onChange={(e) => setStartsOn(e.target.value)} />
        </label>
        <label>
          Melyik hónapot tervezitek
          <select value={month} onChange={(e) => setMonth(e.target.value)}>
            {options.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
          </select>
        </label>
      </div>
      {error && <p className="error">{error}</p>}
      <button className="btn primary big block" style={{ marginTop: 12 }} disabled={busy} onClick={start}>
        {monthLabel(month)} indítása
      </button>
    </Card>
  );
}

function FullMeeting({ status }: { status: BudgetStatus }) {
  const current = status.current!;
  const [reload, setReload] = useState(0);
  const month = useAsync(() => api.budgetMonth(), [reload]);
  const refresh = () => setReload((n) => n + 1);
  const [next, setNext] = useState(status.suggested_month);

  return (
    <>
      <p className="muted" style={{ marginTop: 0 }}>
        Lezárjátok: <strong>{monthLabel(current.month)}</strong> ({periodRange(current)}).
        Utána indul: <strong>{monthLabel(next)}</strong>.
      </p>
      {!status.meeting_due && (
        <p className="badge" style={{ marginTop: 0, whiteSpace: "normal" }}>
          Még nem esedékes – {monthLabel(current.month).toLowerCase()} már meg van tervezve. A
          következő megbeszélés {monthLabel(next).toLowerCase()} elején jön; addig ez az oldal
          csak áttekintés.
        </p>
      )}

      <AsyncBlock state={month}>
        {(data) => (
          <>
            <Issues data={data} onChange={refresh}
                    title={`1. Ami nyitva maradt – ${monthLabel(current.month)}`} />
            <PlanVsActual data={data} />
          </>
        )}
      </AsyncBlock>

      <SettleStep />
      <NextMonth month={next} />
      <CloseStep status={status} next={next} setNext={setNext} />
    </>
  );
}

function PlanVsActual({ data }: { data: MonthView }) {
  // Only what can go over: spending rows with a plan or with spending. A yearly bill paid
  // this month is not an overspend, and money set aside has no "actual" to compare.
  const rows = data.rows
    .filter((r) => r.actual !== null && !r.yearly && !(r.type === "line" && isAside(r.kind)))
    .filter((r) => Number(r.plan) > 0 || Number(r.actual) > 0)
    .map((r) => ({ ...r, diff: Number(r.actual) - Number(r.plan) }))
    .sort((a, b) => b.diff - a.diff);

  return (
    <Card title="2. Terv és tény" note="a legnagyobb túllépés elöl">
      {rows.length === 0 ? (
        <p className="muted" style={{ margin: 0 }}>Ebben az időszakban nem volt se terv, se költés.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Sor</th><th className="num">Terv</th><th className="num">Tény</th><th className="num">Eltérés</th></tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key}>
                  <td>
                    {row.name}
                    <div className="muted small">{ownerName(data.users, row.owner_id)}</div>
                  </td>
                  <td className="num">{ft(row.plan)}</td>
                  <td className="num">{ft(row.actual)}</td>
                  <td className={`num ${row.diff > 0 ? "neg" : ""}`}>
                    {row.diff > 0 ? "+" : ""}{ft(row.diff)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small" style={{ marginBottom: 0 }}>
        Összesen {ft(data.totals.spent)} a tervezett {ft(data.totals.planned_spending)}-ból. Ami nem
        fogyott el, nem viszitek át a következő hónapra.
      </p>
    </Card>
  );
}

function SettleStep() {
  const [reload, setReload] = useState(0);
  const summary = useAsync(() => api.splitSummary(), [reload]);
  const me = useSession()?.user_id ?? null;
  return (
    <Card title="3. Elszámolás">
      <AsyncBlock state={summary}>
        {(data) => data.transfers.length === 0 ? (
          <p style={{ margin: 0 }}>✓ Kvittek vagytok.</p>
        ) : (
          <>
            {data.transfers.map((transfer) => (
              <Debt key={`${transfer.from_user_id}-${transfer.to_user_id}`} transfer={transfer} me={me}
                    onSettled={() => setReload((n) => n + 1)} />
            ))}
            <Link className="small" to="/elszamolas">A megosztott blokkok →</Link>
          </>
        )}
      </AsyncBlock>
    </Card>
  );
}

function NextMonth({ month }: { month: string }) {
  const [reload, setReload] = useState(0);
  const plan = useAsync(() => api.plan(month, 1), [month, reload]);
  return (
    <Card title={`4. ${monthLabel(month)} terve`} note="a többi hónap ezt örökli">
      <AsyncBlock state={plan}>
        {(data) => <NextMonthBody data={data} onSaved={() => setReload((n) => n + 1)} />}
      </AsyncBlock>
    </Card>
  );
}

function NextMonthBody({ data, onSaved }: { data: Plan; onSaved: () => void }) {
  const month = data.months[0];
  const lines = data.rows.filter((r) => r.type === "line" && r.active);
  const automatic = data.rows.filter((r) => r.type === "recurring");
  const totals = data.totals[0];
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setValues(Object.fromEntries(lines.map((r) => [r.id, plain(r.cells[0].amount)])));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const recurringTotal = useMemo(
    () => automatic.reduce((sum, r) => sum + Number(r.cells[0].amount), 0), [automatic],
  );

  async function save(lineId: string, before: string) {
    const raw = values[lineId] ?? "";
    if (raw === before) return;
    const value = amountOf(raw);
    if (value === null || value < 0) {
      setError("Nem értelmezhető összeg.");
      return;
    }
    try {
      await api.setPlanAmount(lineId, month.month, value);
      setError(null);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (month.locked) {
    return <p className="muted" style={{ margin: 0 }}>Ez a hónap le van zárva.</p>;
  }

  return (
    <>
      {lines.length === 0 ? (
        <p className="muted" style={{ marginTop: 0 }}>
          Még nincs keret. A sorokat a <Link to="/terv">Terv</Link> alatt veheted fel.
        </p>
      ) : (
        lines.map((row) => (
          <div key={row.id} className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
            <span style={{ flex: "1 1 150px" }}>
              {row.name}
              <span className="muted small"> · {ownerName(data.users, row.owner_id)}</span>
            </span>
            <input
              style={{ width: "9em", padding: "9px 10px", border: "1px solid var(--border)", borderRadius: 8,
                       background: "var(--surface-raised)", fontSize: 16, textAlign: "right", minHeight: 44 }}
              inputMode="decimal"
              aria-label={`${row.name} kerete`}
              value={values[row.id] ?? ""}
              onChange={(e) => setValues({ ...values, [row.id]: e.target.value })}
              onBlur={() => save(row.id, plain(row.cells[0].amount))}
              onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
            />
          </div>
        ))
      )}
      {error && <p className="error">{error}</p>}
      {automatic.length > 0 && (
        <p className="muted small">
          Rendszeres kiadások (maguktól számolnak): {ft(recurringTotal)}
        </p>
      )}
      <div className="row" style={{ justifyContent: "space-between", fontWeight: 650 }}>
        <span>Szabad – háztartás</span>
        <span className={Number(totals.free) < 0 ? "neg" : undefined}>{ft(totals.free)}</span>
      </div>
      {totals.people.map((p) => (
        <div key={p.user_id} className="row small" style={{ justifyContent: "space-between" }}>
          <span>Szabad – {ownerName(data.users, p.user_id)}</span>
          <span className={Number(p.free) < 0 ? "neg" : undefined}>{ft(p.free)}</span>
        </div>
      ))}
    </>
  );
}

function CloseStep({ status, next, setNext }: {
  status: BudgetStatus; next: string; setNext: (month: string) => void;
}) {
  const navigate = useNavigate();
  const current = status.current!;
  const [startsOn, setStartsOn] = useState(status.today);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const options = [1, 2, 3].map((n) => addMonths(current.month, n));
  if (!options.includes(next)) options.unshift(next);
  const proposed = useAsync(() => api.proposedTransfers(next), [next]);
  const overview = useAsync(() => api.pocketsOverview(), []);
  // Per proposed transfer: whether it was sent (ticked by default) and how much (D28).
  const [sent, setSent] = useState<Record<string, { done: boolean; amount: string }>>({});
  const [checks, setChecks] = useState<Record<string, string>>({});
  const users = overview.data?.users ?? [];
  const keyOf = (t: ProposedTransfer) => `${t.line_id}:${t.from_user_id ?? ""}`;

  useEffect(() => {
    setSent(Object.fromEntries((proposed.data ?? []).map((t) => [keyOf(t), { done: true, amount: plain(t.amount) }])));
  }, [proposed.data]);

  async function close() {
    setBusy(true);
    setError(null);
    try {
      const transfers = (proposed.data ?? []).map((t) => {
        const state = sent[keyOf(t)] ?? { done: true, amount: plain(t.amount) };
        return { line_id: t.line_id, from_user_id: t.from_user_id, amount: amountOf(state.amount) ?? 0, done: state.done };
      });
      const balances = Object.entries(checks)
        .filter(([, v]) => v.trim() !== "")
        .map(([pocket_id, v]) => ({ pocket_id, balance: amountOf(v) ?? 0 }));
      await api.openPeriod({ starts_on: startsOn, month: next, transfers, checks: balances });
      navigate("/penz");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <Card title="5. Lezárás">
      <div className="grid cols-2" style={{ gap: 10 }}>
        <label>
          A megbeszélés napja – innen indul az új időszak
          <input type="date" value={startsOn} max={status.today} min={current.starts_on}
                 onChange={(e) => setStartsOn(e.target.value)} />
        </label>
        <label>
          Az új időszak
          <select value={next} onChange={(e) => setNext(e.target.value)}>
            {options.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
          </select>
        </label>
      </div>
      {(overview.data?.pockets.length ?? 0) > 0 && (
        <>
          <h3 style={{ margin: "14px 0 6px" }}>Mennyi van most a zsebekben?</h3>
          <p className="muted small" style={{ marginTop: 0 }}>
            Írd be a Revolut szerinti egyenleget, ha megnézted – az app összeveti a sajátjával.
          </p>
          {overview.data!.pockets.map((view) => (
            <div key={view.pocket.id} className="row" style={{ justifyContent: "space-between", marginBottom: 6 }}>
              <span style={{ flex: "1 1 150px" }}>
                {pocketLabel(view.pocket, users)}
                <span className="muted small"> · app szerint {ft(view.closing)}</span>
              </span>
              <input
                style={{ width: "9em", padding: "9px 10px", border: "1px solid var(--border)", borderRadius: 8,
                         background: "var(--surface-raised)", fontSize: 16, textAlign: "right", minHeight: 44 }}
                inputMode="decimal" placeholder="Revolut" aria-label={`${view.pocket.name} a Revolut szerint`}
                value={checks[view.pocket.id] ?? ""}
                onChange={(e) => setChecks({ ...checks, [view.pocket.id]: e.target.value })}
              />
            </div>
          ))}
        </>
      )}

      {(proposed.data?.length ?? 0) > 0 && (
        <>
          <h3 style={{ margin: "14px 0 6px" }}>Átutalások a zsebekbe – {monthLabel(next).toLowerCase()}</h3>
          <p className="muted small" style={{ marginTop: 0 }}>
            Ami be van pipálva, azt elküldöttnek veszi. Ami nincs, az a Hónap teendői között vár,
            amíg el nem küldöd.
          </p>
          {proposed.data!.map((t) => {
            const state = sent[keyOf(t)] ?? { done: true, amount: plain(t.amount) };
            const set = (patch: Partial<typeof state>) => setSent({ ...sent, [keyOf(t)]: { ...state, ...patch } });
            return (
              <div key={keyOf(t)} className="occ-row">
                <label className="row" style={{ flex: "1 1 180px", display: "flex", gap: 8, color: "var(--ink)", fontSize: "0.95rem" }}>
                  <input type="checkbox" checked={state.done} style={{ width: "auto", minHeight: 0 }}
                         onChange={(e) => set({ done: e.target.checked })} />
                  <span>
                    {ownerName(users, t.from_user_id)} → {pocketLabel({ name: t.pocket_name, holder_id: t.holder_id }, users)}
                    <span className="muted small"> · {t.line_name}</span>
                  </span>
                </label>
                <div className="occ-actions">
                  <input inputMode="decimal" aria-label={`${t.line_name} átutalás`} value={state.amount}
                         onChange={(e) => set({ amount: e.target.value })} />
                </div>
              </div>
            );
          })}
        </>
      )}

      <p className="muted small">
        A lezárt hónap terve befagy; ha később javítani kell, a Hónap oldalon újranyitható.
      </p>
      {error && <p className="error">{error}</p>}
      <button className="btn primary big block" disabled={busy} onClick={close}>
        {monthLabel(current.month)} lezárása, {monthLabel(next)} indítása
      </button>
    </Card>
  );
}
