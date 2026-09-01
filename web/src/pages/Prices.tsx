/** The save-money screen: what individual things cost, where, and how that is moving. */

import { useState } from "react";

import { api } from "../lib/api";
import { IndexChart, MAX_SERIES, PriceHistoryChart, RankingChart } from "../lib/charts";
import { date, ft, month, pct } from "../lib/format";
import { AsyncBlock, Card, Empty, useAsync } from "../components/ui";

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
                        {[...data.points].reverse().map((point) => (
                          <tr key={`${point.receipt_id}-${point.purchased_at}`}>
                            <td className="mono">{date(point.purchased_at)}</td>
                            <td>{point.merchant_name}</td>
                            <td className="num">{ft(point.unit_price)}</td>
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
                Ehhez legalább két bolt kell, közös termékekkel. Társíts több tételt termékhez.
              </Empty>
            ) : (
              <>
                <p className="muted" style={{ marginTop: 0 }}>
                  {data.product_count} olyan termék alapján, amit mindegyik boltban megvettél már.
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
