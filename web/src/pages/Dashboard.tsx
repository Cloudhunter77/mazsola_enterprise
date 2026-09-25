import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { MonthlySpendChart, RankingChart } from "../lib/charts";
import { ft, month } from "../lib/format";
import { AsyncBlock, Card, Tile, useAsync } from "../components/ui";

export default function Dashboard() {
  const summary = useAsync(() => api.summary(), []);
  const monthly = useAsync(() => api.monthly(), []);
  const categories = useAsync(() => api.byCategory(), []);
  const merchants = useAsync(() => api.byMerchant(), []);

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
              <RankingChart
                data={data.slice(0, 10).map((row) => ({
                  label: row.category_name,
                  value: Number(row.total),
                  note: `${(row.share * 100).toFixed(1)}% · ${row.item_count} tétel`,
                }))}
              />
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
                          <td>{row.category_name}</td>
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
            <RankingChart
              data={data.map((row) => ({
                label: row.merchant_name,
                value: Number(row.total),
                note: `${row.receipt_count} blokk · átlag ${ft(row.average_basket)}`,
              }))}
            />
          )}
        </AsyncBlock>
      </Card>
    </>
  );
}
