/** The spreadsheet view: one row per receipt - date, shop, amount paid.
 *
 *  Everything else in the app is a considered view of the data. This is the data: sortable,
 *  filterable, totalled at the top, and exportable to CSV when you want it somewhere else.
 *  A row is a receipt however it got here - photographed, typed in, or generated from a
 *  subscription - because for "what did I spend" that distinction does not matter.
 */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, type ReceiptSummary } from "../lib/api";
import { ft, date as fmtDate } from "../lib/format";
import { AsyncBlock, Card, Tile, useAsync } from "../components/ui";

type SortKey = "date" | "shop" | "amount";

const SOURCES: Record<string, string> = {
  web: "Fotó",
  shortcut: "Parancs",
  folder: "Mappa",
  manual: "Kézi",
  recurring: "Előfizetés",
};

/** Receipts with no trustworthy total have no business in a spending table. */
const READY = new Set(["parsed", "needs_review", "confirmed"]);

export default function TableView() {
  // One generous page rather than pagination: a few thousand rows is nothing for the
  // browser, and scrolling a table beats clicking through it.
  const receipts = useAsync(() => api.receipts({ limit: 200 }), []);
  const [sort, setSort] = useState<SortKey>("date");
  const [descending, setDescending] = useState(true);
  const [query, setQuery] = useState("");

  // Sorting and filtering happen here, not inside AsyncBlock's render callback: that
  // callback is not always invoked, so a hook called from it would be a conditional hook.
  const rows = useRows(receipts.data ?? [], query, sort, descending);
  const total = rows.reduce((sum, row) => sum + Number(row.total_gross ?? 0), 0);

  function sortBy(key: SortKey) {
    if (key === sort) setDescending((d) => !d);
    else {
      setSort(key);
      setDescending(key === "date" || key === "amount");
    }
  }

  return (
    <>
      <div className="row" style={{ marginBottom: 14 }}>
        <h1 style={{ flex: 1 }}>Tábla</h1>
        <Link className="btn" to="/kezi">+ Kézi</Link>{" "}
        <Link className="btn" to="/elofizetesek">Előfizetések</Link>{" "}
        <a className="btn" href={api.exportCsvUrl()}>CSV</a>{" "}
        <Link className="btn" to="/rendszer" title="Verzió és állapot">⚙</Link>
      </div>

      <AsyncBlock state={receipts} empty="Még nincs rögzített kiadás.">
        {() => (
          <>
              <div className="grid tiles" style={{ marginBottom: 14 }}>
                <Tile label="Sorok" value={rows.length} />
                <Tile label="Összesen" value={ft(total)} />
                <Tile
                  label="Átlag"
                  value={rows.length ? ft(total / rows.length) : "–"}
                />
              </div>

              <Card>
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Szűrés boltra…"
                  aria-label="Szűrés boltra"
                  style={{ width: "100%" }}
                />

                <div className="table-wrap" style={{ marginTop: 12 }}>
                  <table>
                    <thead>
                      <tr>
                        <Th label="Dátum" active={sort === "date"} desc={descending}
                            onClick={() => sortBy("date")} />
                        <Th label="Bolt" active={sort === "shop"} desc={descending}
                            onClick={() => sortBy("shop")} />
                        <Th label="Összeg" numeric active={sort === "amount"} desc={descending}
                            onClick={() => sortBy("amount")} />
                        <th>Forrás</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={row.id}>
                          <td style={{ whiteSpace: "nowrap" }}>
                            <Link to={`/blokkok/${row.id}`}>
                              {row.purchased_at ? fmtDate(row.purchased_at) : "–"}
                            </Link>
                          </td>
                          <td>
                            {row.merchant_name ?? "Ismeretlen"}
                            {row.review_reasons?.length ? (
                              <span className="badge warn" style={{ marginLeft: 6 }}>⚠</span>
                            ) : null}
                          </td>
                          <td className="num">{ft(row.total_gross)}</td>
                          <td className="muted">{SOURCES[row.source] ?? row.source}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {rows.length === 0 && (
                  <p className="muted" style={{ marginBottom: 0 }}>
                    Nincs találat erre a szűrésre.
                  </p>
                )}
              </Card>
          </>
        )}
      </AsyncBlock>
    </>
  );
}

function useRows(
  data: ReceiptSummary[], query: string, sort: SortKey, descending: boolean,
): ReceiptSummary[] {
  return useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = data.filter(
      (row) =>
        READY.has(row.status) &&
        (!needle || (row.merchant_name ?? "").toLowerCase().includes(needle)),
    );

    const direction = descending ? -1 : 1;
    return [...filtered].sort((a, b) => {
      if (sort === "amount") {
        return direction * (Number(a.total_gross ?? 0) - Number(b.total_gross ?? 0));
      }
      if (sort === "shop") {
        return direction * (a.merchant_name ?? "").localeCompare(b.merchant_name ?? "", "hu");
      }
      // Undated receipts sort to the end whichever way the column points, rather than
      // taking over the top of the table.
      const left = a.purchased_at ?? "";
      const right = b.purchased_at ?? "";
      if (!left || !right) return left ? -1 : right ? 1 : 0;
      return direction * left.localeCompare(right);
    });
  }, [data, query, sort, descending]);
}

function Th({ label, active, desc, numeric, onClick }: {
  label: string; active: boolean; desc: boolean; numeric?: boolean; onClick: () => void;
}) {
  return (
    <th
      className={numeric ? "num" : undefined}
      onClick={onClick}
      style={{ cursor: "pointer", userSelect: "none" }}
      aria-sort={active ? (desc ? "descending" : "ascending") : "none"}
    >
      {label}{active ? (desc ? " ↓" : " ↑") : ""}
    </th>
  );
}
