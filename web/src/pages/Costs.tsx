/** What the automatic reading has cost.
 *
 *  Deliberately its own screen: the choice between an expensive accurate model and a
 *  cheap one is only sensible with the real per-receipt figure in front of you.
 */

import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { month } from "../lib/format";
import { AsyncBlock, Card, Tile, useAsync } from "../components/ui";

const usd = (value: string | number) => `$${Number(value).toFixed(4)}`;

export default function Costs() {
  const costs = useAsync(() => api.costs(), []);

  return (
    <>
      <div className="row" style={{ marginBottom: 14 }}>
        <h1 style={{ flex: 1 }}>Felismerési költség</h1>
        <Link className="btn" to="/statisztika">← Statisztika</Link>
      </div>

      <AsyncBlock state={costs} empty="Még nem futott felismerés.">
        {(data) => (
          <>
            <div className="grid tiles" style={{ marginBottom: 14 }}>
              <Tile label="Összesen" value={`$${Number(data.total_usd).toFixed(2)}`}
                    sub={`${data.receipts_extracted} blokk`} />
              <Tile label="Blokkonként" value={usd(data.average_usd)} />
              <Tile label="Éves szinten" value={`$${Number(data.projected_yearly_usd).toFixed(2)}`}
                    sub="az eddigi ütem alapján" />
              <Tile label="Sikertelen hívás" value={data.failures} />
            </div>

            <Card title="Havonta és modellenként">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Hónap</th>
                      <th>Modell</th>
                      <th className="num">Blokk</th>
                      <th className="num">Összeg</th>
                      <th className="num">Blokkonként</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_month.map((row) => (
                      <tr key={`${row.month}-${row.model}`}>
                        <td>{month(row.month)}</td>
                        <td className="mono">{row.model ?? "–"}</td>
                        <td className="num">{row.receipts}</td>
                        <td className="num">${Number(row.total_usd).toFixed(4)}</td>
                        <td className="num">{usd(row.avg_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            <Card title="Olcsóbbra váltás">
              <p style={{ marginTop: 0 }}>
                A modell egyetlen környezeti változó – <code>OPENROUTER_MODEL</code>, illetve
                közvetlen Anthropic-kapcsolatnál <code>EXTRACTOR_MODEL</code>. Egy olcsóbb modell
                töredékébe kerül, cserébe több blokk kerül ellenőrzésre.
              </p>
              <p className="muted" style={{ marginBottom: 0 }}>
                Váltás után ezen az oldalon és az „Ellenőrzendő” számon látszik, megérte-e: ha az
                ellenőrzésre váró blokkok aránya nem nő, a drágább modellre nincs szükség.
              </p>
            </Card>
          </>
        )}
      </AsyncBlock>
    </>
  );
}
