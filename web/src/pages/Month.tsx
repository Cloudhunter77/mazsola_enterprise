/** Hónap: the current period at a glance.
 *
 *  Income in against what is expected, every line's plan against what was actually spent,
 *  and what still needs doing - a salary nobody marked as arrived, receipts without a
 *  category, a bill that looks shared but was never split. Grouped by whose money it is:
 *  Közös first, then each of you.
 *
 *  Any earlier period can be opened from the picker. A closed one can be reopened to fix
 *  its plan, then closed again.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api, type MonthRow, type MonthView, type Person } from "../lib/api";
import { KIND_LABELS, dayLabel, isAside, monthLabel, ownerName, owners, periodRange } from "../lib/budget";
import { ft } from "../lib/format";
import Occurrences from "../components/Occurrences";
import { AsyncBlock, Card, Tile, useAsync } from "../components/ui";

export default function Month() {
  const [periodId, setPeriodId] = useState<string | undefined>(undefined);
  const [reload, setReload] = useState(0);
  const view = useAsync(() => api.budgetMonth(periodId), [periodId, reload]);
  const refresh = () => setReload((n) => n + 1);

  if (view.error && /Még nincs időszak/.test(view.error)) return <NoPeriodYet />;

  return (
    <AsyncBlock state={view}>
      {(data) => <MonthBody data={data} onPick={setPeriodId} onChange={refresh} />}
    </AsyncBlock>
  );
}

function NoPeriodYet() {
  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Hónap</h1>
      <Card>
        <p style={{ marginTop: 0 }}>
          A költségvetés időszakokban számol: egy időszak az egyik havi megbeszéléstől a
          következőig tart. Az első megbeszéléssel indul.
        </p>
        <p className="muted small">
          Előtte érdemes a <Link to="/rendszeres">Rendszeres</Link> alatt felvenni a fizetéseket és
          a havi számlákat, és a <Link to="/terv">Terv</Link>ben a kereteket – a megbeszélés
          ezekből dolgozik.
        </p>
        <Link className="btn primary block" to="/megbeszeles">Az első időszak indítása →</Link>
      </Card>
    </>
  );
}

function MonthBody({ data, onPick, onChange }: {
  data: MonthView; onPick: (id: string) => void; onChange: () => void;
}) {
  const { period, totals } = data;
  const [busy, setBusy] = useState(false);
  const left = Number(totals.planned_spending) - Number(totals.spent);
  const openIssues =
    data.issues.due.filter((o) => o.direction !== "income").length +
    data.issues.uncategorised.length + data.issues.maybe_shared.length + data.issues.late.length;

  async function toggleClosed() {
    setBusy(true);
    try {
      if (period.closed_at) await api.reopenPeriod(period.id);
      else await api.closePeriod(period.id);
      onChange();
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="row" style={{ marginBottom: 14, alignItems: "baseline", justifyContent: "space-between" }}>
        <div>
          <h1>{monthLabel(period.month)}</h1>
          <div className="muted small">
            {periodRange(period)}
            {period.is_current ? " · folyamatban" : period.closed_at ? " · lezárva" : " · újranyitva"}
          </div>
        </div>
        {data.periods.length > 1 && (
          <label style={{ minWidth: 170 }}>
            <span className="sr-only">Időszak</span>
            <select value={period.id} onChange={(e) => onPick(e.target.value)}>
              {data.periods.map((p) => (
                <option key={p.id} value={p.id}>{monthLabel(p.month)} · {periodRange(p)}</option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div className="grid tiles" style={{ marginBottom: 14 }}>
        <Tile
          label="Bevétel"
          value={ft(totals.income_arrived)}
          sub={`várható összesen ${ft(totals.income_expected)}`}
        />
        <Tile
          label="Elköltve"
          value={ft(totals.spent)}
          sub={`terv: ${ft(totals.planned_spending)}`}
        />
        <Tile
          label={left >= 0 ? "Még elkölthető" : "Túlköltés"}
          value={<span className={left < 0 ? "neg" : undefined}>{ft(Math.abs(left))}</span>}
          sub="a tervezett keretekből"
        />
        <Tile
          label="Szabad a tervben"
          value={<span className={Number(totals.free) < 0 ? "neg" : undefined}>{ft(totals.free)}</span>}
          sub={Number(totals.planned_aside) > 0 ? `félretéve: ${ft(totals.planned_aside)}` : "bevétel − minden terv"}
        />
      </div>

      {period.is_current ? (
        <Link className={`btn block ${data.meeting_due ? "primary" : ""}`} to="/megbeszeles"
              style={{ marginBottom: 14 }}>
          Havi megbeszélés →
        </Link>
      ) : (
        <button className="btn block" style={{ marginBottom: 14 }} disabled={busy} onClick={toggleClosed}>
          {period.closed_at ? "Újranyitás javításhoz" : "Lezárás újra"}
        </button>
      )}

      {/* Salaries waiting to be confirmed are in the Bevételek card just below. */}
      {openIssues > 0 && <Issues data={data} onChange={onChange} includeIncome={false} />}

      <IncomeCard data={data} onChange={onChange} />

      {owners(data.users).map((owner) => {
        const rows = data.rows.filter((row) => row.owner_id === owner.id);
        if (rows.length === 0) return null;
        const plan = rows.filter((r) => !isAside(r.kind) || r.type !== "line")
          .reduce((sum, r) => sum + Number(r.plan), 0);
        const spent = rows.reduce((sum, r) => sum + Number(r.actual ?? 0), 0);
        return (
          <Card key={owner.id ?? "kozos"} title={owner.name} note={`${ft(spent)} / ${ft(plan)}`}>
            {rows.map((row) => <BudgetRow key={row.key} row={row} />)}
          </Card>
        );
      })}

      {data.rows.length === 0 && (
        <Card>
          <p className="muted" style={{ margin: 0 }}>
            Ebben az időszakban még nincs se terv, se költés. A kereteket a{" "}
            <Link to="/terv">Terv</Link> alatt veheted fel.
          </p>
        </Card>
      )}

      <p className="muted small" style={{ textAlign: "center" }}>
        {data.receipt_count} blokk ebben az időszakban · <Link to="/terv">keretek szerkesztése →</Link>
      </p>
    </>
  );
}

function BudgetRow({ row }: { row: MonthRow }) {
  const [open, setOpen] = useState(false);
  const plan = Number(row.plan);
  const actual = row.actual === null ? null : Number(row.actual);
  const over = actual !== null && plan > 0 && actual > plan && !row.yearly;
  const used = actual !== null && plan > 0 ? Math.min(100, (actual / plan) * 100) : actual ? 100 : 0;

  return (
    <div className="budget-row">
      <button className="head" onClick={() => setOpen(!open)} aria-expanded={open}
              disabled={row.receipts.length === 0}>
        <span style={{ minWidth: 0 }}>
          {row.type === "recurring" && <span aria-hidden>↻ </span>}
          {row.name}
          {row.type !== "unplanned" && <span className="tag">{KIND_LABELS[row.kind]}</span>}
          {row.yearly && <span className="tag">éves · 1/12</span>}
          {!row.active && <span className="tag">archivált</span>}
        </span>
        <span className="figures">
          {actual === null ? (
            <span className="muted">félretéve: {ft(plan)}</span>
          ) : row.type === "unplanned" ? (
            <span className="neg">{ft(actual)}</span>
          ) : (
            <>
              <span className={over ? "neg" : undefined}>{ft(actual)}</span>
              <span className="muted"> / {ft(plan)}</span>
            </>
          )}
        </span>
      </button>
      {actual !== null && row.type !== "unplanned" && (plan > 0 || actual > 0) && (
        <div className={`meter ${over ? "over" : ""}`} aria-hidden><span style={{ width: `${used}%` }} /></div>
      )}
      {actual !== null && row.type !== "unplanned" && plan > 0 && (
        <div className="small muted" style={{ marginTop: 4 }}>
          {row.yearly
            ? "évente fizetendő; a tervben havi tizede szerepel"
            : over ? <span className="neg">{ft(actual - plan)}-tal túllépve</span>
              : `még ${ft(plan - actual)}`}
        </div>
      )}
      {open && (
        <ul className="pieces">
          {row.receipts.map((piece, index) => (
            <li key={`${piece.receipt_id}-${index}`}>
              <Link to={`/blokkok/${piece.receipt_id}`}>
                {dayLabel(piece.day)} · {piece.merchant ?? "?"}
              </Link>
              <span className="mono">{ft(piece.amount)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function IncomeCard({ data, onChange }: { data: MonthView; onChange: () => void }) {
  const pending = data.occurrences.filter(
    (o) => o.direction === "income" && (o.status === "expected" || o.status === "due"),
  );
  return (
    <Card title="Bevételek" action={<Link className="btn" to="/kezi?bevetel">+ Bevétel</Link>}>
      {data.income.length === 0 && pending.length === 0 ? (
        <p className="muted" style={{ margin: 0 }}>
          Ebben az időszakban még nincs bevétel. A fizetéseket a{" "}
          <Link to="/rendszeres">Rendszeres</Link> alatt érdemes beállítani.
        </p>
      ) : (
        <>
          {data.income.map((owner) => (
            <div key={owner.owner_id ?? "kozos"} className="row" style={{ justifyContent: "space-between", marginBottom: 6 }}>
              <span>{ownerName(data.users, owner.owner_id)}</span>
              <span className="mono">
                {ft(owner.arrived)}
                {Number(owner.expected) > Number(owner.arrived) && (
                  <span className="muted"> / {ft(owner.expected)} várható</span>
                )}
              </span>
            </div>
          ))}
          {pending.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <Occurrences items={pending} users={data.users} onChange={onChange} />
            </div>
          )}
          {data.income_entries.length > 0 && (
            <details style={{ marginTop: 8 }}>
              <summary className="muted small" style={{ cursor: "pointer" }}>
                {data.income_entries.length} bevétel ebben az időszakban
              </summary>
              <ul className="pieces" style={{ listStyle: "none", padding: 0 }}>
                {data.income_entries.map((entry) => (
                  <IncomeLine key={entry.id} entry={entry} users={data.users} onChange={onChange} />
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </Card>
  );
}

function IncomeLine({ entry, users, onChange }: {
  entry: MonthView["income_entries"][number]; users: Person[]; onChange: () => void;
}) {
  async function remove() {
    if (!window.confirm(`Törlöd: ${entry.name}, ${ft(entry.amount)}?`)) return;
    await api.deleteIncome(entry.id);
    onChange();
  }
  return (
    <li className="row" style={{ justifyContent: "space-between", padding: "4px 0" }}>
      <span>
        {dayLabel(entry.received_on)} · {entry.name}
        <span className="muted"> · {ownerName(users, entry.user_id)}</span>
      </span>
      <span className="row" style={{ gap: 6 }}>
        <span className="mono">{ft(entry.amount)}</span>
        <button className="btn" aria-label="Bevétel törlése" onClick={remove}>✕</button>
      </span>
    </li>
  );
}

/** What a meeting should look at: shown here as soon as it exists, not only at the meeting. */
export function Issues({ data, onChange, title = "Teendők", includeIncome = true }: {
  data: MonthView; onChange: () => void; title?: string; includeIncome?: boolean;
}) {
  const { uncategorised, maybe_shared: shared, late } = data.issues;
  const due = data.issues.due.filter((o) => includeIncome || o.direction !== "income");
  const unsortedTotal = uncategorised.reduce((sum, p) => sum + Number(p.amount), 0);
  return (
    <Card title={title}>
      {due.length > 0 && (
        <>
          <h3 style={{ marginBottom: 6 }}>Rendszeres tételek, amikről még nem tudjuk, mi lett</h3>
          <Occurrences items={due} users={data.users} onChange={onChange} />
        </>
      )}
      {uncategorised.length > 0 && (
        <p>
          <Link to="/kategorizalas">
            {uncategorised.length} blokkban van besorolatlan tétel ({ft(unsortedTotal)}) – kategorizálás →
          </Link>
        </p>
      )}
      {shared.length > 0 && (
        <>
          <h3 style={{ margin: "12px 0 6px" }}>Lehet, hogy közös – nincs megosztva</h3>
          <p className="muted small" style={{ marginTop: 0 }}>
            A fizetőnek nincs rá saját kerete, a közösnek van. Ha közös volt, oszd meg a blokkot.
          </p>
          <ul className="pieces" style={{ listStyle: "none", padding: 0 }}>
            {shared.map((piece) => (
              <li key={piece.receipt_id} className="row" style={{ justifyContent: "space-between", padding: "4px 0" }}>
                <Link to={`/blokkok/${piece.receipt_id}`}>{dayLabel(piece.day)} · {piece.merchant ?? "?"}</Link>
                <span className="mono">{ft(piece.amount)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {late.length > 0 && (
        <>
          <h3 style={{ margin: "12px 0 6px" }}>Zárás után rögzítve</h3>
          <ul className="pieces" style={{ listStyle: "none", padding: 0 }}>
            {late.map((piece) => (
              <li key={piece.receipt_id} className="row" style={{ justifyContent: "space-between", padding: "4px 0" }}>
                <Link to={`/blokkok/${piece.receipt_id}`}>
                  {dayLabel(piece.day)} · {piece.merchant ?? "?"}
                  <span className="muted"> · {monthLabel(piece.period_month)}</span>
                </Link>
                <span className="mono">{ft(piece.amount)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {due.length + uncategorised.length + shared.length + late.length === 0 && (
        <p style={{ margin: 0 }}>✓ Minden rendben, nincs nyitott tétel.</p>
      )}
    </Card>
  );
}
