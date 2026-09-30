/** Clearing out "Besorolatlan", a receipt at a time.
 *
 *  The receipt is the unit you remember: a restaurant bill, a pharmacy visit, a hardware
 *  run is one kind of spending however many lines it prints, so it takes one choice. A
 *  mixed supermarket shop is the exception, and it keeps what the keywords already filed -
 *  only the blanks follow your choice - with the receipt's own screen a tap away for
 *  anything that needs going through line by line.
 *
 *  Choosing saves at once, because a second confirm tap per row is what makes a list like
 *  this get abandoned. The cost of that is a mis-tap, so every row can be taken back.
 */

import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, type Category, type ReceiptFiling, type ReceiptToFile } from "../lib/api";
import { date, ft } from "../lib/format";
import { AsyncBlock, Card, useAsync } from "../components/ui";

type Done = { filing: ReceiptFiling; categoryName: string };

export default function Categorise() {
  const [reload, setReload] = useState(0);
  const list = useAsync(() => api.receiptsToFile(), [reload]);
  const categories = useAsync(() => api.categories(), []);

  // The rows as first loaded, kept in place while you work so filing one does not make the
  // rest jump. `gone` are receipts another answer filed for you - the same shop, once you
  // told it what it always means - and `done` the ones you filed yourself.
  const [snapshot, setSnapshot] = useState<ReceiptToFile[] | null>(null);
  const [gone, setGone] = useState<Set<string>>(new Set());
  const [done, setDone] = useState<Record<string, Done>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!list.data) return;
    if (snapshot === null) {
      setSnapshot(list.data);
      return;
    }
    const still = new Set(list.data.map((row) => row.receipt_id));
    setGone(new Set(snapshot.filter((r) => !still.has(r.receipt_id)).map((r) => r.receipt_id)));
  }, [list.data]); // eslint-disable-line react-hooks/exhaustive-deps

  async function file(row: ReceiptToFile, category: Category, rememberShop: boolean) {
    setBusy(row.receipt_id);
    setError(null);
    try {
      const filing = await api.fileReceipt(row.receipt_id, category.id, rememberShop);
      setDone((current) => ({ ...current, [row.receipt_id]: { filing, categoryName: category.name } }));
      // The shop's other receipts may have followed; ask which, so they leave the list.
      if (filing.spread > 0) setReload((n) => n + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function undo(row: ReceiptToFile) {
    const entry = done[row.receipt_id];
    if (!entry) return;
    setBusy(row.receipt_id);
    setError(null);
    try {
      await api.undoFiling(entry.filing);
      setDone((current) => {
        const next = { ...current };
        delete next[row.receipt_id];
        return next;
      });
      setReload((n) => n + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const rows = (snapshot ?? []).filter((row) => done[row.receipt_id] || !gone.has(row.receipt_id));
  const left = rows.filter((row) => !done[row.receipt_id]);

  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Kategorizálás</h1>

      <AsyncBlock state={list} empty="Nincs besorolatlan tétel – minden a helyén van.">
        {() => (
          <Card
            title="Besorolatlan blokkok"
            note={`${left.length} blokk · ${ft(left.reduce((sum, r) => sum + Number(r.uncategorised_amount), 0))}`}
          >
            <p className="muted" style={{ marginTop: 0, fontSize: "0.86rem" }}>
              Válassz kategóriát a blokknak, és minden még besorolatlan tétele oda kerül. Ami
              már be van sorolva, az marad. Vegyes bevásárlásnál nyisd meg a blokkot, és
              sorold be tételenként.
            </p>
            {error && <p className="error">{error}</p>}

            {rows.map((row) => (
              <Row
                key={row.receipt_id}
                row={row}
                done={done[row.receipt_id]}
                busy={busy === row.receipt_id}
                categories={categories.data ?? []}
                onFile={file}
                onUndo={undo}
              />
            ))}
          </Card>
        )}
      </AsyncBlock>
    </>
  );
}

function Row({ row, done, busy, categories, onFile, onUndo }: {
  row: ReceiptToFile;
  done: Done | undefined;
  busy: boolean;
  categories: Category[];
  onFile: (row: ReceiptToFile, category: Category, rememberShop: boolean) => void;
  onUndo: (row: ReceiptToFile) => void;
}) {
  const groups = useMemo(() => grouped(categories), [categories]);
  // Off by default: for a supermarket it would be wrong, and a default filed wrongly is
  // silent. For a restaurant or a pharmacy it is one tick that saves every future receipt.
  const [rememberShop, setRememberShop] = useState(false);
  const shop = row.merchant_name ?? "Ismeretlen bolt";
  const all = row.uncategorised_lines === row.item_lines;

  return (
    <div style={{ borderTop: "1px solid var(--grid)", paddingTop: 12, marginTop: 12 }}>
      <div className="row" style={{ gap: 8, alignItems: "baseline", opacity: done ? 0.6 : 1 }}>
        <Link to={`/blokkok/${row.receipt_id}`} style={{ flex: 1, fontWeight: 600 }}>
          {shop}
          <span className="muted" style={{ fontWeight: 400 }}> · {date(row.purchased_at)}</span>
        </Link>
        <span className="num" style={{ whiteSpace: "nowrap" }}>{ft(row.total_gross)}</span>
      </div>
      <div className="muted" style={{ fontSize: "0.8rem" }}>
        {all
          ? `mind a ${row.item_lines} tétel besorolatlan`
          : `${row.uncategorised_lines} / ${row.item_lines} tétel besorolatlan`}
        {" · "}{ft(row.uncategorised_amount)}
      </div>
      <div className="muted" style={{ fontSize: "0.8rem", marginBottom: 8 }}>
        {row.names.join(" · ")}
        {row.uncategorised_lines > row.names.length && " · …"}
      </div>

      {done ? (
        <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ flex: "1 1 100%", color: "var(--good-text)", fontSize: "0.9rem" }}>
            ✓ {done.categoryName} · {done.filing.lines} tétel
            {done.filing.merchant_id && (
              <span className="muted">
                {" "}· {shop} mostantól mindig ez
                {done.filing.spread > 0 && ` (+${done.filing.spread} tétel a többi blokkján)`}
              </span>
            )}
          </span>
          <button className="btn" disabled={busy} onClick={() => onUndo(row)}>
            Visszavonás
          </button>
        </div>
      ) : (
        <>
          {row.merchant_id && (
            <label
              style={{
                display: "flex", alignItems: "center", gap: 10, minHeight: 40,
                fontSize: "0.88rem", cursor: "pointer",
              }}
            >
              <input
                type="checkbox"
                checked={rememberShop}
                onChange={(event) => setRememberShop(event.target.checked)}
                disabled={busy}
                style={{ width: 22, height: 22, flex: "0 0 auto" }}
              />
              <span>{shop} mindig ez legyen – a többi blokkja is</span>
            </label>
          )}
          <select
            value=""
            disabled={busy || categories.length === 0}
            aria-label={`${shop} ${date(row.purchased_at)} kategóriája`}
            style={{ width: "100%" }}
            onChange={(event) => {
              const category = categories.find((c) => c.id === event.target.value);
              if (category) onFile(row, category, rememberShop);
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
        </>
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
