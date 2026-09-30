/** Clearing out "Besorolatlan".
 *
 *  The automatic rules file what they recognise and leave the rest blank on purpose - a
 *  wrong category is the quiet kind of wrong. This is where the blank goes to be dealt with:
 *  each printed name once, most money first, so the top of the list is where an answer moves
 *  the dashboard most.
 *
 *  Picking a category saves at once, because on a phone a second confirm tap per row is the
 *  difference between clearing the list and giving up on it. The cost of that is a mis-tap,
 *  so every row can be taken back until you leave the page.
 */

import { useEffect, useMemo, useState } from "react";

import {
  api,
  type Category,
  type CategoryAssignment,
  type UncategorisedName,
} from "../lib/api";
import { date, ft } from "../lib/format";
import { AsyncBlock, Card, useAsync } from "../components/ui";

type Done = { assignment: CategoryAssignment; categoryName: string };

export default function Categorise() {
  const [reload, setReload] = useState(0);
  const list = useAsync(() => api.uncategorised(), [reload]);
  const categories = useAsync(() => api.categories(), []);

  // The rows as first loaded, kept in place while you work so filing one does not make the
  // rest jump. `gone` are names that another answer filed on your behalf - a second
  // spelling of the same product - and `done` the ones you filed yourself.
  const [snapshot, setSnapshot] = useState<UncategorisedName[] | null>(null);
  const [gone, setGone] = useState<Set<string>>(new Set());
  const [done, setDone] = useState<Record<string, Done>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!list.data) return;
    if (snapshot === null) {
      setSnapshot(list.data);
      return;
    }
    const still = new Set(list.data.map((row) => row.raw_name));
    setGone(new Set(snapshot.filter((row) => !still.has(row.raw_name)).map((r) => r.raw_name)));
  }, [list.data]); // eslint-disable-line react-hooks/exhaustive-deps

  async function assign(row: UncategorisedName, category: Category) {
    setBusy(row.raw_name);
    setError(null);
    try {
      const assignment = await api.assignCategory(row.raw_name, category.id);
      setDone((current) => ({
        ...current,
        [row.raw_name]: { assignment, categoryName: category.name },
      }));
      // Others may have been filed along with it; ask which, so they leave the list.
      if (assignment.spread > 0) setReload((n) => n + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function undo(row: UncategorisedName) {
    const entry = done[row.raw_name];
    if (!entry) return;
    setBusy(row.raw_name);
    setError(null);
    try {
      await api.undoCategory(entry.assignment);
      setDone((current) => {
        const next = { ...current };
        delete next[row.raw_name];
        return next;
      });
      setReload((n) => n + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const needle = query.trim().toLowerCase();
  const rows = (snapshot ?? []).filter(
    (row) =>
      (done[row.raw_name] || !gone.has(row.raw_name)) &&
      (!needle || row.raw_name.toLowerCase().includes(needle)),
  );
  const left = (snapshot ?? []).filter((row) => !done[row.raw_name] && !gone.has(row.raw_name));

  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Kategorizálás</h1>

      <AsyncBlock state={list} empty="Nincs besorolatlan tétel – minden a helyén van.">
        {() => (
          <Card
            title="Besorolatlan tételek"
            note={`${left.length} név · ${ft(left.reduce((sum, row) => sum + Number(row.total), 0))}`}
          >
            <p className="muted" style={{ marginTop: 0, fontSize: "0.86rem" }}>
              Válassz kategóriát, és az összes így nevezett tétel oda kerül – a korábbiak is.
              A hozzá tartozó termék is megtanulja, így a következő blokkon már magától
              besorolódik. Amit már kézzel beállítottál, azt nem írja felül.
            </p>

            {(snapshot?.length ?? 0) > 8 && (
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Keresés a nevek között"
                aria-label="Keresés"
                style={{ width: "100%", marginBottom: 6 }}
              />
            )}
            {error && <p className="error">{error}</p>}

            {rows.map((row) => (
              <Row
                key={row.raw_name}
                row={row}
                done={done[row.raw_name]}
                busy={busy === row.raw_name}
                categories={categories.data ?? []}
                onAssign={assign}
                onUndo={undo}
              />
            ))}
            {rows.length === 0 && needle && (
              <p className="muted" style={{ marginBottom: 0 }}>Nincs ilyen nevű tétel.</p>
            )}
          </Card>
        )}
      </AsyncBlock>
    </>
  );
}

function Row({ row, done, busy, categories, onAssign, onUndo }: {
  row: UncategorisedName;
  done: Done | undefined;
  busy: boolean;
  categories: Category[];
  onAssign: (row: UncategorisedName, category: Category) => void;
  onUndo: (row: UncategorisedName) => void;
}) {
  const groups = useMemo(() => grouped(categories), [categories]);

  return (
    <div style={{ borderTop: "1px solid var(--grid)", paddingTop: 10, marginTop: 10 }}>
      <div style={{ fontWeight: 600, opacity: done ? 0.6 : 1 }}>{row.raw_name}</div>
      <div className="muted" style={{ fontSize: "0.8rem", marginBottom: 8 }}>
        {row.lines}× · {ft(row.total)}
        {row.last_bought && <> · utoljára {date(row.last_bought)}</>}
        {row.product_name && <> · termék: {row.product_name}</>}
      </div>

      {done ? (
        <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ flex: "1 1 100%", color: "var(--good-text)", fontSize: "0.9rem" }}>
            ✓ {done.categoryName} · {done.assignment.lines} tétel
            {done.assignment.spread > 0 && (
              <span className="muted"> (ebből {done.assignment.spread} más írásmóddal)</span>
            )}
          </span>
          <button className="btn" disabled={busy} onClick={() => onUndo(row)}>
            Visszavonás
          </button>
        </div>
      ) : (
        <select
          value=""
          disabled={busy || categories.length === 0}
          aria-label={`${row.raw_name} kategóriája`}
          style={{ width: "100%" }}
          onChange={(event) => {
            const category = categories.find((c) => c.id === event.target.value);
            if (category) onAssign(row, category);
          }}
        >
          <option value="" disabled>
            {busy ? "Mentés…" : "Kategória választása…"}
          </option>
          {groups.map(({ parent, children }) => (
            <optgroup key={parent.id} label={parent.name}>
              <option value={parent.id}>{parent.name}</option>
              {children.map((child) => (
                <option key={child.id} value={child.id}>{child.name}</option>
              ))}
            </optgroup>
          ))}
        </select>
      )}
    </div>
  );
}

/** The tree as the picker shows it: each main category with its subcategories beneath. */
function grouped(categories: Category[]) {
  const order = (a: Category, b: Category) =>
    a.sort_order - b.sort_order || a.name.localeCompare(b.name, "hu");
  return categories
    .filter((category) => category.parent_id === null)
    .sort(order)
    .map((parent) => ({
      parent,
      children: categories.filter((c) => c.parent_id === parent.id).sort(order),
    }));
}
