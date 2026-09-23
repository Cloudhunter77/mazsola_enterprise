/** What the automatic reading has cost.
 *
 *  Deliberately its own screen: the choice between an expensive accurate model and a
 *  cheap one is only sensible with the real per-receipt figure in front of you.
 */

import { Link } from "react-router-dom";

import { api, type AttemptKind } from "../lib/api";
import { month } from "../lib/format";
import { AsyncBlock, Card, Tile, useAsync } from "../components/ui";

const usd = (value: string | number) => `$${Number(value).toFixed(4)}`;

// Averages per receipt. These are the number to look at when the bill surprises you: the
// per-receipt cost is just tokens x the model's rate, so an unexpected total is nearly
// always an unexpected input-token count rather than the model being dearer than thought.
const tokens = (value: number | null) => (value == null ? "–" : value.toLocaleString("hu-HU"));

// What was being read. Naming these in the user's own words matters more here than usual:
// "product_photo" is a column name, "termékfotó" is the thing you did on Saturday.
const KINDS: Record<AttemptKind, string> = {
  receipt: "Blokk",
  price_label: "Árcímke",
  product_photo: "Termékfotó",
};
const kindName = (kind: string) => KINDS[kind as AttemptKind] ?? kind;

export default function Costs() {
  const costs = useAsync(() => api.costs(), []);

  return (
    <>
      <div className="row page-actions" style={{ marginBottom: 14 }}>
        <h1 style={{ flex: 1 }}>Felismerési költség</h1>
        <Link className="btn" to="/statisztika">← Statisztika</Link>
      </div>

      <AsyncBlock state={costs} empty="Még nem futott felismerés.">
        {(data) => (
          <>
            <div className="grid tiles" style={{ marginBottom: 14 }}>
              <Tile label="Összesen" value={`$${Number(data.total_usd).toFixed(2)}`}
                    sub={`${data.calls} hívás`} />
              <Tile label="Hívásonként" value={usd(data.average_usd)} />
              <Tile label="Éves szinten" value={`$${Number(data.projected_yearly_usd).toFixed(2)}`}
                    sub="az eddigi ütem alapján" />
              <Tile label="Sikertelen hívás" value={data.failures} />
            </div>

            <Card title="Mire megy el" note="a drágább szokás elöl">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Mit olvasott</th>
                      <th className="num">Hívás</th>
                      <th className="num">Össze&shy;sen</th>
                      <th className="num">Hívásonként</th>
                      <th className="num">Token be</th>
                      <th className="num">Token ki</th>
                      <th className="num">Sikertelen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_kind.map((row) => (
                      <tr key={row.kind}>
                        <td>{kindName(row.kind)}</td>
                        <td className="num">{row.calls}</td>
                        <td className="num">${Number(row.total_usd).toFixed(4)}</td>
                        <td className="num">{usd(row.avg_usd)}</td>
                        <td className="num">{tokens(row.avg_input_tokens)}</td>
                        <td className="num">{tokens(row.avg_output_tokens)}</td>
                        <td className="num">{row.failures || "–"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted" style={{ marginBottom: 0 }}>
                Egy összeg csak azt mondja meg, mennyibe kerül az alkalmazás. Ez a bontás azt,
                hogy melyik szokás kerül pénzbe – és a váltás előtt ez a kérdés.
              </p>
            </Card>

            <Card title="Havonta és modellenként">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Hónap</th>
                      <th>Mit olvasott</th>
                      <th>Modell</th>
                      <th className="num">Hívás</th>
                      <th className="num">Össze&shy;sen</th>
                      <th className="num">Hívásonként</th>
                      <th className="num">Token be</th>
                      <th className="num">Token ki</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_month.map((row) => (
                      <tr key={`${row.month}-${row.kind}-${row.model}`}>
                        <td>{month(row.month)}</td>
                        <td>{kindName(row.kind)}</td>
                        <td className="mono">{row.model ?? "–"}</td>
                        <td className="num">{row.calls}</td>
                        <td className="num">${Number(row.total_usd).toFixed(4)}</td>
                        <td className="num">{usd(row.avg_usd)}</td>
                        <td className="num">{tokens(row.avg_input_tokens)}</td>
                        <td className="num">{tokens(row.avg_output_tokens)}</td>
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
              <p className="muted">
                Váltás után ezen az oldalon és az „Ellenőrzendő” számon látszik, megérte-e: ha az
                ellenőrzésre váró blokkok aránya nem nő, a drágább modellre nincs szükség.
              </p>
              <p className="muted" style={{ marginBottom: 0 }}>
                Ha a blokkonkénti összeg magasabb a vártnál, előbb a token-oszlopokat nézd meg. A
                bemeneti tokenek nagy részét a fénykép adja: a <code>MAX_IMAGE_EDGE</code>{" "}
                csökkentése 1600-ról 1280-ra nagyjából a felére viszi. Olcsóbb modellek listáját a{" "}
                <code>scripts/list_models.py</code> adja, épp erre a token-mennyiségre számolva.
              </p>
            </Card>
          </>
        )}
      </AsyncBlock>
    </>
  );
}
