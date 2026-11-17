import { useState } from "react";
import { Link } from "react-router-dom";

import { api, type CategorySpend, type MerchantSpend } from "../lib/api";
import { MonthlySpendChart, RankingChart } from "../lib/charts";
import { STATUS_LABELS, date, ft, month, qty } from "../lib/format";
import { AsyncBlock, Card, Loading, Tile, useAsync } from "../components/ui";

export default function Dashboard() {
  const summary = useAsync(() => api.summary(), []);
  const monthly = useAsync(() => api.monthly(), []);
  const categories = useAsync(() => api.byCategory(), []);
  const merchants = useAsync(() => api.byMerchant(), []);
  // Which bar was tapped: the list of what makes it up opens below its chart.
  const [category, setCategory] = useState<CategorySpend | null>(null);
  const [shop, setShop] = useState<MerchantSpend | null>(null);

  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Statisztika</h1>

      <AsyncBlock state={summary}>
        {(data) => (
          <div className="grid tiles" style={{ marginBottom: 14 }}>
            <Tile label="Összes költés" value={ft(data.total)} sub={`${data.receipt_count} blokk`} />
            <Tile label="Átlagos kosár" value={ft(data.average_basket)} />
            <Tile label="Rögzített tétel" value={data.item_count.toLocaleString("hu-HU")} />
            <Tile
              label="Ellenőrzendő"
              value={data.pending_review}
              sub={
                data.pending_review > 0 ? (
                  <Link to="/blokkok">megnyitás →</Link>
                ) : (
                  "minden rendben"
                )
              }
            />
          </div>
        )}
      </AsyncBlock>

      <Card title="Havi költés" note="minden feldolgozott blokk">
        <AsyncBlock state={monthly} empty="Még nincs feldolgozott blokk.">
          {(data) => (
            <MonthlySpendChart
              data={data.map((row) => ({
                label: month(row.month),
                total: Number(row.total),
                receipts: row.receipt_count,
              }))}
            />
          )}
        </AsyncBlock>
      </Card>

      <Card title="Kategóriák" note="csak termék sorok">
        <AsyncBlock state={categories} empty="Sorolj be tételeket kategóriába a blokk nézetben.">
          {(data) => (
            <>
              <Uncategorised rows={data} />
              <RankingChart
                data={data.slice(0, 10).map((row) => ({
                  label: row.category_name,
                  value: Number(row.total),
                  note: `${(row.share * 100).toFixed(1)}% · ${row.item_count} tétel`,
                }))}
                onSelect={(index) => setCategory(category === data[index] ? null : data[index])}
                selected={category ? data.indexOf(category) : null}
              />
              <p className="muted small" style={{ margin: "4px 0 0" }}>
                Koppints egy sávra: megmutatja, mely tételekből jön ki.
              </p>
              {category && (
                <CategoryLines category={category} onClose={() => setCategory(null)} />
              )}
              {/* The table is the accessible companion to the chart, and the place
                  to read exact values. */}
              <details style={{ marginTop: 10 }}>
                <summary className="muted" style={{ cursor: "pointer", fontSize: "0.84rem" }}>
                  Számok táblázatban
                </summary>
                <div className="table-wrap" style={{ marginTop: 8 }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Kategória</th>
                        <th className="num">Összeg</th>
                        <th className="num">Arány</th>
                        <th className="num">Tétel</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.map((row) => (
                        <tr key={row.category_id ?? "none"}>
                          <td>
                            <button className="link-button" onClick={() => setCategory(row)}>
                              {row.category_name}
                            </button>
                          </td>
                          <td className="num">{ft(row.total)}</td>
                          <td className="num">{(row.share * 100).toFixed(1)}%</td>
                          <td className="num">{row.item_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </>
          )}
        </AsyncBlock>
      </Card>

      <Card title="Boltok">
        <AsyncBlock state={merchants} empty="Még nincs bolt.">
          {(data) => (
            <>
              <RankingChart
                data={data.map((row) => ({
                  label: row.merchant_name,
                  value: Number(row.total),
                  note: `${row.receipt_count} blokk · átlag ${ft(row.average_basket)}`,
                }))}
                onSelect={(index) => setShop(shop === data[index] ? null : data[index])}
                selected={shop ? data.indexOf(shop) : null}
              />
              {shop && <ShopReceipts shop={shop} onClose={() => setShop(null)} />}
            </>
          )}
        </AsyncBlock>
      </Card>
    </>
  );
}

/** The way out of "Besorolatlan", placed where you notice it. The bar alone told you how much
 *  was uncategorised and gave you nowhere to go about it. */
function Uncategorised({ rows }: { rows: CategorySpend[] }) {
  const blank = rows.find((row) => row.category_id === null);
  if (!blank) return null;
  return (
    <Link
      className="btn block"
      to="/kategorizalas"
      style={{ marginBottom: 12, justifyContent: "space-between" }}
    >
      <span>
        {blank.item_count} tétel besorolatlan
        <span className="muted"> · {ft(blank.total)}</span>
      </span>
      <span>Kategorizálás →</span>
    </Link>
  );
}

/** What one category bar is made of: its lines, the largest first, each a tap from its
 *  receipt. A total that looks wrong is nearly always one misread line, and it is on top. */
function CategoryLines({ category, onClose }: { category: CategorySpend; onClose: () => void }) {
  const lines = useAsync(() => api.categoryLines(category.category_id), [category.category_id]);
  return (
    <div className="drill">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>{category.category_name}: {ft(category.total)}</strong>
        <button className="btn" onClick={onClose} aria-label="Bezárás">✕</button>
      </div>
      {lines.loading && !lines.data ? <Loading /> : lines.error ? (
        <p className="error">{lines.error}</p>
      ) : (
        <ul className="pieces">
          {(lines.data ?? []).map((line) => (
            <li key={line.item_id}>
              <Link to={`/blokkok/${line.receipt_id}`} style={{ minWidth: 0 }}>
                {line.raw_name}
                <span className="muted">
                  {" "}· {line.merchant_name ?? "?"} · {date(line.purchased_at)}
                  {line.quantity && Number(line.quantity) !== 1 ? ` · ${qty(line.quantity, line.unit)}` : ""}
                  {line.status === "needs_review" ? ` · ${STATUS_LABELS.needs_review}` : ""}
                </span>
              </Link>
              <span className="mono">{ft(line.gross_amount)}</span>
            </li>
          ))}
        </ul>
      )}
      {category.item_count > (lines.data?.length ?? 0) && (
        <p className="muted small">A {lines.data?.length} legnagyobb a {category.item_count} tételből.</p>
      )}
    </div>
  );
}

function ShopReceipts({ shop, onClose }: { shop: MerchantSpend; onClose: () => void }) {
  const receipts = useAsync(() => api.merchantReceipts(shop.merchant_id), [shop.merchant_id]);
  return (
    <div className="drill">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>{shop.merchant_name}: {ft(shop.total)}</strong>
        <button className="btn" onClick={onClose} aria-label="Bezárás">✕</button>
      </div>
      {receipts.loading && !receipts.data ? <Loading /> : receipts.error ? (
        <p className="error">{receipts.error}</p>
      ) : (
        <ul className="pieces">
          {(receipts.data ?? []).map((r) => (
            <li key={r.receipt_id}>
              <Link to={`/blokkok/${r.receipt_id}`}>
                {date(r.purchased_at)}
                {r.status === "needs_review" && <span className="muted"> · {STATUS_LABELS.needs_review}</span>}
              </Link>
              <span className="mono">{ft(r.total_gross)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
