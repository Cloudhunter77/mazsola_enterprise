/** Terv: the plan for the coming months.
 *
 *  Lines down the side, months across, as in the spreadsheet this replaces - and like
 *  there, an amount carries forward until you change it. A muted number is carried forward;
 *  a number in full ink was set in that month. Tap a cell to change it from that month on.
 *  Recurring bills and salaries fill their own rows from Rendszeres and are not edited here.
 *
 *  At the bottom, what is left free: expected income minus everything planned, for the
 *  household and for each of you, with the Közös plan divided equally. A month that does
 *  not add up turns red.
 */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, type BudgetLine, type Category, type LineKind, type Plan, type PlanRow } from "../lib/api";
import { KINDS, KIND_LABELS, amountOf, monthLabel, monthShort, owners, ownerName, plain } from "../lib/budget";
import { groupCategories } from "../lib/categories";
import { ft } from "../lib/format";
import { AsyncBlock, Card, useAsync } from "../components/ui";

const addMonths = (iso: string, count: number): string => {
  const [y, m] = iso.split("-").map(Number);
  const index = y * 12 + (m - 1) + count;
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}-01`;
};

type Editing = { lineId: string; month: string; value: string } | null;
type LineDraft = {
  id: string | null; name: string; owner_id: string; kind: LineKind;
  category_ids: string[]; amount: string; active: boolean;
};

export default function PlanPage() {
  const [start, setStart] = useState<string | undefined>(undefined);
  const [reload, setReload] = useState(0);
  const plan = useAsync(() => api.plan(start, 6), [start, reload]);
  const lines = useAsync(() => api.budgetLines(), [reload]);
  const categories = useAsync(() => api.categories(), []);
  const [draft, setDraft] = useState<LineDraft | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const refresh = () => setReload((n) => n + 1);

  const first = plan.data?.months[0]?.month;

  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Terv</h1>

      {draft ? (
        <LineForm
          draft={draft} setDraft={setDraft} plan={plan.data} lines={lines.data ?? []}
          categories={categories.data ?? []} firstMonth={first}
          onDone={() => { setDraft(null); refresh(); }}
        />
      ) : (
        <Card>
          <p className="muted" style={{ marginTop: 0 }}>
            Egy összeg a következő hónapokra öröklődik, amíg át nem írod. A halvány szám
            öröklött, a teljes színű abban a hónapban lett beállítva. Egy cellára koppintva
            attól a hónaptól kezdve módosítod.
          </p>
          <div className="row">
            <button className="btn primary" onClick={() => setDraft({
              id: null, name: "", owner_id: "", kind: "valtozo", category_ids: [], amount: "", active: true,
            })}>
              + Új sor
            </button>
            <label className="row" style={{ gap: 6, fontSize: "0.88rem", display: "flex" }}>
              <input type="checkbox" checked={showArchived} style={{ width: "auto", minHeight: 0 }}
                     onChange={(e) => setShowArchived(e.target.checked)} />
              archivált sorok is
            </label>
          </div>
        </Card>
      )}

      <AsyncBlock state={plan}>
        {(data) => (
          <Card
            title={`${monthLabel(data.months[0].month)} – ${monthLabel(data.months[data.months.length - 1].month)}`}
            action={
              <div className="row" style={{ gap: 6 }}>
                <button className="btn" aria-label="Korábbi hónapok"
                        onClick={() => setStart(addMonths(data.months[0].month, -1))}>‹</button>
                <button className="btn" aria-label="Későbbi hónapok"
                        onClick={() => setStart(addMonths(data.months[0].month, 1))}>›</button>
              </div>
            }
          >
            <Grid
              data={data} showArchived={showArchived} onChanged={refresh}
              onEditLine={(row) => {
                const line = lines.data?.find((l) => l.id === row.id);
                if (!line) return;
                setDraft({
                  id: line.id, name: line.name, owner_id: line.owner_id ?? "", kind: line.kind,
                  category_ids: line.category_ids, amount: "", active: line.active,
                });
                window.scrollTo(0, 0);
              }}
            />
          </Card>
        )}
      </AsyncBlock>
    </>
  );
}

function Grid({ data, showArchived, onChanged, onEditLine }: {
  data: Plan; showArchived: boolean; onChanged: () => void; onEditLine: (row: PlanRow) => void;
}) {
  const [editing, setEditing] = useState<Editing>(null);
  const [error, setError] = useState<string | null>(null);
  const columns = data.months.length + 1;

  async function save() {
    if (!editing) return;
    const raw = editing.value.trim();
    const value = raw === "" ? null : amountOf(raw);
    if (raw !== "" && (value === null || value < 0)) {
      setError("Nem értelmezhető összeg.");
      return;
    }
    try {
      await api.setPlanAmount(editing.lineId, editing.month, value);
      setEditing(null);
      setError(null);
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const visible = data.rows.filter((row) => row.type !== "line" || row.active || showArchived);
  const spending = (owner: string | null) => visible.filter((r) => r.type !== "income" && r.owner_id === owner);
  const income = visible.filter((r) => r.type === "income");

  const sum = (rows: PlanRow[], index: number) =>
    rows.reduce((total, row) => total + Number(row.cells[index].amount), 0);

  return (
    <>
      {error && <p className="error">{error}</p>}
      <div className="table-wrap">
        <table className="plan-grid">
          <thead>
            <tr>
              <th>Sor</th>
              {data.months.map((m) => (
                <th key={m.month} className="month" title={m.locked ? "Lezárt időszak" : undefined}>
                  {m.locked && "🔒 "}{monthShort(m.month)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {owners(data.users).map((owner) => {
              const rows = spending(owner.id);
              if (rows.length === 0) return null;
              return (
                <OwnerGroup key={owner.id ?? "kozos"} title={owner.name} rows={rows} data={data}
                            columns={columns} editing={editing} setEditing={setEditing}
                            save={save} onEditLine={onEditLine} sum={sum} />
              );
            })}

            <GroupRow title="Bevételek" columns={columns} />
            {income.length === 0 ? (
              <tr>
                <td className="muted small">
                  Nincs rendszeres bevétel – <Link to="/rendszeres">felvétel a Rendszeres alatt</Link>.
                </td>
                <td colSpan={columns - 1} />
              </tr>
            ) : income.map((row) => (
              <tr key={row.key}>
                <td>
                  <Link to="/rendszeres">{row.name}</Link>
                  <div className="muted small">{ownerName(data.users, row.owner_id)}</div>
                </td>
                {row.cells.map((cell, i) => <td key={i} className="cell">{ft(cell.amount)}</td>)}
              </tr>
            ))}

            <GroupRow title="Mi marad" columns={columns} />
            <tr className="sum">
              <td>Bevétel</td>
              {data.totals.map((t, i) => <td key={i} className="cell">{ft(t.income)}</td>)}
            </tr>
            <tr className="sum">
              <td>Tervezve</td>
              {data.totals.map((t, i) => <td key={i} className="cell">{ft(t.planned)}</td>)}
            </tr>
            <tr className="sum">
              <td>Szabad – háztartás</td>
              {data.totals.map((t, i) => (
                <td key={i} className={`cell ${Number(t.free) < 0 ? "neg" : ""}`}>{ft(t.free)}</td>
              ))}
            </tr>
            {data.users.filter((u) => u.active).map((user) => (
              <tr key={user.id}>
                <td>Szabad – {user.display_name}</td>
                {data.totals.map((t, i) => {
                  const mine = t.people.find((p) => p.user_id === user.id);
                  const free = Number(mine?.free ?? 0);
                  return <td key={i} className={`cell ${free < 0 ? "neg" : ""}`}>{ft(free)}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small" style={{ marginBottom: 0 }}>
        Egy személy szabad összege: a saját bevétele, mínusz a saját sorai, mínusz a közös terv
        egyenlő része (egy megosztott rendszeres tételnél a megosztás szerinti része).
      </p>
    </>
  );
}

function OwnerGroup({ title, rows, data, columns, editing, setEditing, save, onEditLine, sum }: {
  title: string; rows: PlanRow[]; data: Plan; columns: number;
  editing: Editing; setEditing: (e: Editing) => void; save: () => void;
  onEditLine: (row: PlanRow) => void; sum: (rows: PlanRow[], index: number) => number;
}) {
  return (
    <>
      <GroupRow title={title} columns={columns} />
      {rows.map((row) => (
        <tr key={row.key} style={{ opacity: row.active ? 1 : 0.55 }}>
          <td>
            {row.type === "line" ? (
              <button className="line-name" onClick={() => onEditLine(row)}>{row.name}</button>
            ) : (
              <Link to="/rendszeres">↻ {row.name}</Link>
            )}
            <span className="tag">{KIND_LABELS[row.kind]}</span>
            {row.yearly && <span className="tag">1/12</span>}
          </td>
          {row.cells.map((cell, i) => {
            const month = data.months[i];
            const isEditing = editing?.lineId === row.id && editing.month === month.month;
            const editable = row.type === "line" && !month.locked && row.active;
            return (
              <td key={month.month} className={`cell ${cell.explicit ? "" : "inherited"}`}>
                {isEditing ? (
                  <input
                    autoFocus inputMode="decimal" value={editing.value}
                    aria-label={`${row.name}, ${monthLabel(month.month)}`}
                    onChange={(e) => setEditing({ ...editing, value: e.target.value })}
                    onBlur={save}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") save();
                      if (e.key === "Escape") setEditing(null);
                    }}
                  />
                ) : editable ? (
                  <button
                    className="cell-btn"
                    aria-label={`${row.name}, ${monthLabel(month.month)}: ${ft(cell.amount)}`}
                    onClick={() => setEditing({ lineId: row.id, month: month.month, value: plain(cell.amount) })}
                  >
                    {ft(cell.amount)}
                  </button>
                ) : (
                  ft(cell.amount)
                )}
              </td>
            );
          })}
        </tr>
      ))}
      <tr className="sum">
        <td className="muted">Összesen</td>
        {data.months.map((m, i) => <td key={m.month} className="cell muted">{ft(sum(rows, i))}</td>)}
      </tr>
    </>
  );
}

/** A heading row. Its title is an ordinary first cell rather than one spanning the row, so it
 *  stays pinned with the names while the months scroll sideways on a phone. */
function GroupRow({ title, columns }: { title: string; columns: number }) {
  return (
    <tr className="group">
      <td>{title}</td>
      <td colSpan={columns - 1} />
    </tr>
  );
}

function LineForm({ draft, setDraft, plan, lines, categories, firstMonth, onDone }: {
  draft: LineDraft; setDraft: (d: LineDraft | null) => void; plan: Plan | null;
  lines: BudgetLine[]; categories: Category[]; firstMonth: string | undefined;
  onDone: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const groups = useMemo(() => groupCategories(categories), [categories]);
  const set = (patch: Partial<LineDraft>) => setDraft({ ...draft, ...patch });
  const users = plan?.users ?? [];

  // A category already in another active line of the same owner cannot be chosen again.
  const taken = new Map<string, string>();
  for (const line of lines) {
    if (line.id === draft.id || !line.active || (line.owner_id ?? "") !== draft.owner_id) continue;
    for (const id of line.category_ids) taken.set(id, line.name);
  }

  const toggle = (id: string) => set({
    category_ids: draft.category_ids.includes(id)
      ? draft.category_ids.filter((c) => c !== id)
      : [...draft.category_ids, id],
  });

  async function save() {
    setError(null);
    if (!draft.name.trim()) return setError("Adj nevet a sornak.");
    const amount = draft.amount.trim() ? amountOf(draft.amount) : null;
    if (draft.amount.trim() && (amount === null || amount < 0)) return setError("Nem értelmezhető összeg.");
    const body = {
      name: draft.name.trim(), owner_id: draft.owner_id || null, kind: draft.kind,
      category_ids: draft.category_ids, active: draft.active,
    };
    setBusy(true);
    try {
      if (draft.id) await api.updateLine(draft.id, body);
      else await api.createLine({ ...body, amount, from_month: firstMonth });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!draft.id) return;
    const sure = window.confirm(
      `Törlöd a(z) "${draft.name}" sort? Ha egy lezárt hónap már számolt vele, csak archiválódik: ` +
      "ott megmarad, a jövőben nem számít.",
    );
    if (!sure) return;
    await api.removeLine(draft.id);
    onDone();
  }

  return (
    <Card title={draft.id ? "Sor szerkesztése" : "Új sor"}
          action={<button className="btn" onClick={() => setDraft(null)}>Mégse</button>}>
      <div className="grid cols-2" style={{ gap: 10 }}>
        <label>
          Név
          <input value={draft.name} onChange={(e) => set({ name: e.target.value })}
                 placeholder="pl. Kaja – bevásárlás" autoFocus />
        </label>
        <label>
          Kié
          <select value={draft.owner_id} onChange={(e) => set({ owner_id: e.target.value })}>
            {owners(users).map((o) => <option key={o.id ?? "kozos"} value={o.id ?? ""}>{o.name}</option>)}
          </select>
        </label>
        <label>
          Csoport
          <select value={draft.kind} onChange={(e) => set({ kind: e.target.value as LineKind })}>
            {KINDS.map((kind) => <option key={kind} value={kind}>{KIND_LABELS[kind]}</option>)}
          </select>
        </label>
        {!draft.id && (
          <label>
            Havi összeg{firstMonth ? ` ${monthLabel(firstMonth).toLowerCase()}-tól` : ""}
            <input inputMode="decimal" value={draft.amount} placeholder="pl. 120 000"
                   onChange={(e) => set({ amount: e.target.value })} />
          </label>
        )}
      </div>

      <div style={{ marginTop: 12 }}>
        <div className="small" style={{ color: "var(--ink-secondary)", marginBottom: 5 }}>
          Kategóriák – a főkategória az alkategóriáit is viszi
          {(draft.kind === "celalap" || draft.kind === "megtakaritas") && " (félretételnél nem kell)"}
        </div>
        <div className="cat-picker">
          {groups.map(({ parent, children }) => (
            <div key={parent.id}>
              <CategoryBox id={parent.id} name={parent.name} checked={draft.category_ids.includes(parent.id)}
                           taken={taken.get(parent.id)} onToggle={toggle} />
              {children.map((child) => (
                <CategoryBox key={child.id} id={child.id} name={child.name} child
                             checked={draft.category_ids.includes(child.id)}
                             taken={taken.get(child.id)} onToggle={toggle} />
              ))}
            </div>
          ))}
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn primary" disabled={busy} onClick={save}>{busy ? "Mentés…" : "Mentés"}</button>
        {draft.id && !draft.active && (
          <button className="btn" disabled={busy} onClick={() => set({ active: true })}>
            Visszaállítás (mentéssel)
          </button>
        )}
        {draft.id && <button className="btn danger" disabled={busy} onClick={remove}>Törlés</button>}
      </div>
    </Card>
  );
}

function CategoryBox({ id, name, checked, taken, child, onToggle }: {
  id: string; name: string; checked: boolean; taken?: string; child?: boolean;
  onToggle: (id: string) => void;
}) {
  return (
    <label className={`${child ? "child" : ""} ${taken ? "taken" : ""}`}>
      <input type="checkbox" checked={checked} disabled={!!taken && !checked} onChange={() => onToggle(id)} />
      <span>
        {child ? name : <strong>{name}</strong>}
        {taken && <span className="small"> · {taken}</span>}
      </span>
    </label>
  );
}
