/** The save-money screen: what individual things cost, where, and how that is moving. */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api, type PricePoint } from "../lib/api";
import { IndexChart, MAX_SERIES, PriceHistoryChart, RankingChart } from "../lib/charts";
import { date, ft, month, pct } from "../lib/format";
import { AsyncBlock, Card, Empty, useAsync } from "../components/ui";
import Suggestions from "../components/Suggestions";

/** Put the product you are looking at onto the shopping list.
 *
 *  Sits here because this is where you find out a thing has got dearer, or that another
 *  shop sells it for less - and both of those are moments when you want it on the list.
 */
function AddToList({ productId }: { productId: string }) {
  const [state, setState] = useState<"idle" | "adding" | "added" | "failed">("idle");

  // Back to idle when you move to a different product, so the tick belongs to what is
  // actually on screen.
  const [shownFor, setShownFor] = useState(productId);
  if (shownFor !== productId) {
    setShownFor(productId);
    setState("idle");
  }

  return (
    <button
      className="btn"
      style={{ marginBottom: 10 }}
      disabled={state === "adding"}
      onClick={async () => {
        setState("adding");
        try {
          await api.addToList({ product_id: productId });
          setState("added");
        } catch {
          setState("failed");
        }
      }}
    >
      {state === "added" ? "✓ A listán" : state === "failed" ? "Nem sikerült" : "🛒 Listára"}
    </button>
  );
}

export default function Prices() {
  const tracked = useAsync(() => api.trackedProducts(), []);
  const basket = useAsync(() => api.basket(), []);
  const inflation = useAsync(() => api.inflation(), []);
  const [productId, setProductId] = useState<string>("");

  const selected = productId || tracked.data?.[0]?.id || "";
  const history = useAsync(
    () => (selected ? api.priceHistory(selected) : Promise.resolve(null)),
    [selected],
  );

  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Árak</h1>

      {/* Above the charts on purpose: the charts are empty until lines are mapped to
          products, so this is the thing to do first. */}
      <Suggestions />

      <Card
        title="Egy termék ára az időben"
        action={
          <AsyncBlock state={tracked} empty={null}>
            {(products) =>
              products.length ? (
                <select
                  value={selected}
                  onChange={(event) => setProductId(event.target.value)}
                  style={{ padding: "7px 10px", borderRadius: 8, border: "1px solid var(--border)",
                           background: "var(--surface-raised)", maxWidth: 220 }}
                  aria-label="Termék választása"
                >
                  {products.map((product) => (
                    <option key={product.id} value={product.id}>{product.canonical_name}</option>
                  ))}
                </select>
              ) : null
            }
          </AsyncBlock>
        }
      >
        {selected && <AddToList productId={selected} />}
        {!selected ? (
          <Empty>
            Társíts termékeket a blokkok tételeihez – onnantól itt látszik, hogyan változik az áruk.
          </Empty>
        ) : (
          <AsyncBlock state={history}>
            {(data) =>
              !data || data.points.length === 0 ? (
                <Empty>Ehhez a termékhez még nincs elég adat.</Empty>
              ) : (
                <>
                  <div className="row" style={{ marginBottom: 12, gap: 18 }}>
                    <div>
                      <div className="muted" style={{ fontSize: "0.78rem" }}>Legutóbbi ár</div>
                      <div style={{ fontSize: "1.35rem", fontWeight: 680 }}>{ft(data.latest_price)}</div>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: "0.78rem" }}>Változás az első vásárlás óta</div>
                      <div
                        style={{
                          fontSize: "1.35rem", fontWeight: 680,
                          color: data.change_pct == null ? "var(--ink)"
                            : data.change_pct > 0 ? "var(--critical)" : "var(--good-text)",
                        }}
                      >
                        {pct(data.change_pct)}
                      </div>
                    </div>
                    {data.cheapest_merchant && (
                      <div>
                        <div className="muted" style={{ fontSize: "0.78rem" }}>Legolcsóbb itt volt</div>
                        <div style={{ fontSize: "1.35rem", fontWeight: 680 }}>{data.cheapest_merchant}</div>
                      </div>
                    )}
                  </div>

                  <PriceHistoryChart series={toSeries(data.points)} />

                  <div className="table-wrap" style={{ marginTop: 10, maxHeight: 260, overflowY: "auto" }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Dátum</th>
                          <th>Bolt</th>
                          <th className="num">Egységár</th>
                        </tr>
                      </thead>
                      <tbody>
                        {byOrigin([...data.points].reverse()).map(({ point, count }) => (
                          <tr key={`${point.receipt_id ?? point.observation_id}-${point.unit_price}`}>
                            <td className="mono">
                              <Origin point={point} />
                            </td>
                            <td>
                              {point.merchant_name}
                              {/* A shelf price is what the shop asked, not what you paid - worth
                                  saying, because the two diverge exactly when it matters. */}
                              {point.source === "label" && (
                                <span className="muted" style={{ fontSize: "0.78rem" }}>
                                  {" "}· árcímke{point.is_promotion ? ", akció" : ""}
                                </span>
                              )}
                            </td>
                            <td className="num">
                              {ft(point.unit_price)}
                              {count > 1 && <span className="muted"> · {count}×</span>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )
            }
          </AsyncBlock>
        )}
      </Card>

      <Card title="Hol olcsóbb a kosarad" note="csak a mindenhol megvett termékekre">
        <AsyncBlock state={basket}>
          {(data) =>
            data.product_count === 0 ? (
              <Empty>
                Ehhez legalább két olyan bolt kell, ahol az elmúlt {data.window_days} napban
                ugyanazokat a termékeket vetted. Társíts több tételt termékhez.
              </Empty>
            ) : (
              <>
                <p className="muted" style={{ marginTop: 0 }}>
                  {data.product_count} olyan termék alapján, amit mindegyik boltban megvettél már,
                  az elmúlt {data.window_days} nap árait nézve.
                  {Number(data.potential_saving) > 0 && (
                    <> A legdrágább és a legolcsóbb bolt közti különbség{" "}
                      <strong>{ft(data.potential_saving)}</strong>.</>
                  )}
                </p>
                <RankingChart
                  valueLabel="Kosár ára"
                  data={data.merchants.map((merchant, index) => ({
                    label: index === 0 ? `${merchant.merchant_name} ✓ legolcsóbb` : merchant.merchant_name,
                    value: Number(merchant.basket_total),
                    highlight: index === 0,
                  }))}
                />
              </>
            )
          }
        </AsyncBlock>
      </Card>

      <Card title="Saját infláció" note="a te termékeid árindexe, bázis = 100">
        <AsyncBlock state={inflation}>
          {(data) =>
            data.length < 2 ? (
              <Empty>Legalább két hónapnyi, termékhez társított vásárlás kell hozzá.</Empty>
            ) : (
              <IndexChart
                data={data.map((point) => ({
                  label: month(point.month),
                  index: point.index,
                  products: point.product_count,
                }))}
              />
            )
          }
        </AsyncBlock>
      </Card>
    </>
  );
}

/** Group price points by shop, keeping the busiest shops and folding the rest into "Egyéb",
 *  because the palette is only validated for four simultaneous series. */
/** One row per receipt (or shelf photo) and price, with how many lines it stands for.
 *
 *  Aldi prints every scan as its own line, so two bottles of milk were two identical rows
 *  and the table read as if each purchase had been recorded twice. Collapsed, a real
 *  duplicate - the same receipt uploaded twice - shows as what it is: two rows linking to
 *  two different receipts.
 */
function byOrigin(points: PricePoint[]): { point: PricePoint; count: number }[] {
  const rows: { point: PricePoint; count: number }[] = [];
  const index = new Map<string, number>();
  for (const point of points) {
    const key = `${point.receipt_id ?? point.observation_id}|${point.unit_price}`;
    const at = index.get(key);
    if (at === undefined) {
      index.set(key, rows.length);
      rows.push({ point, count: 1 });
    } else {
      rows[at].count += 1;
    }
  }
  return rows;
}

/** The date, as a way back to where the price came from - so it can be checked. */
function Origin({ point }: { point: PricePoint }) {
  if (point.receipt_id) {
    return (
      <Link to={`/blokkok/${point.receipt_id}`} title="A blokk megnyitása">
        {date(point.purchased_at)}
      </Link>
    );
  }
  if (point.label_photo_id) {
    return (
      <a
        href={api.labelImageUrl(point.label_photo_id)}
        target="_blank"
        rel="noreferrer"
        title="A polccímke fotója"
      >
        {date(point.purchased_at)}
      </a>
    );
  }
  return <>{date(point.purchased_at)}</>;
}

function toSeries(points: { purchased_at: string; merchant_name: string; unit_price: string }[]) {
  const byMerchant = new Map<string, { t: number; price: number }[]>();
  for (const point of points) {
    const list = byMerchant.get(point.merchant_name) ?? [];
    list.push({ t: new Date(point.purchased_at).getTime(), price: Number(point.unit_price) });
    byMerchant.set(point.merchant_name, list);
  }

  const ranked = [...byMerchant.entries()].sort((a, b) => b[1].length - a[1].length);
  const kept = ranked.slice(0, MAX_SERIES).map(([name, series]) => ({ name, points: series }));
  const rest = ranked.slice(MAX_SERIES);

  if (rest.length) {
    kept.push({
      name: "Egyéb",
      points: rest.flatMap(([, series]) => series).sort((a, b) => a.t - b.t),
    });
  }
  return kept;
}
