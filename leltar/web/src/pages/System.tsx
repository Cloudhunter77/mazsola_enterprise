import { api } from "../lib/api";
import { AsyncBlock, Card, Tile, useAsync } from "../components/ui";
import { dateTime, month } from "../lib/format";

/** Which build is running, whether the schema took, and what reading has cost. */
export default function System() {
  const system = useAsync(() => api.system(), []);
  const costs = useAsync(() => api.costs(), []);

  return (
    <>
      <Card title="Rendszer">
        <AsyncBlock state={system}>
          {(info) => (
            <>
              <div className="grid tiles">
                <Tile label="Verzió" value={info.version} sub={info.build.commit?.slice(0, 7) ?? "forrásból"} />
                <Tile
                  label="Séma"
                  value={info.schema.up_to_date ? "naprakész" : "eltérés"}
                  sub={`${info.schema.applied ?? "–"} / ${info.schema.expected ?? "–"}`}
                />
                <Tile label="Motor" value={info.identifier} sub={info.model ?? "–"} />
                <Tile
                  label="Munkás"
                  value={info.worker_enabled ? "fut" : "áll"}
                  sub={`${info.photos.pending} sorban`}
                />
              </div>
              <p className="card-note" style={{ marginTop: 12 }}>
                Kép: {info.build.image ?? "–"} · készült: {dateTime(info.build.built_at)} ·
                {" "}legfeljebb {info.max_image_edge}px, képenként {info.max_items_per_photo} tétel
              </p>
              {!info.schema.up_to_date && (
                <p className="error">
                  A migrációk nem futottak le teljesen. A konténer naplója mondja meg, miért.
                </p>
              )}
            </>
          )}
        </AsyncBlock>
      </Card>

      <Card title="Felismerési költség" note="A képeket olvasó hívások ára">
        <AsyncBlock state={costs}>
          {(data) =>
            data.calls === 0 ? (
              <p className="empty">Még nem futott egyetlen felismerés sem.</p>
            ) : (
              <>
                <div className="grid tiles">
                  <Tile label="Összesen" value={`$${Number(data.total_usd).toFixed(4)}`}
                        sub={`${data.calls} hívás`} />
                  <Tile label="Egy fénykép" value={`$${Number(data.usd_per_photo).toFixed(4)}`} />
                  <Tile
                    label="Egy megerősített tétel"
                    value={
                      data.usd_per_confirmed_item == null
                        ? "–"
                        : `$${Number(data.usd_per_confirmed_item).toFixed(4)}`
                    }
                    sub={`${data.confirmed_items} tétel`}
                  />
                  <Tile label="Sikertelen" value={data.failures} sub="ezeket is kiszámlázzák" />
                </div>

                <div className="table-wrap" style={{ marginTop: 14 }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Hónap</th><th>Modell</th>
                        <th className="num">Hívás</th>
                        <th className="num">Talált tétel</th>
                        <th className="num">USD</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.by_month.map((row) => (
                        <tr key={`${row.month}-${row.model}`}>
                          <td>{month(row.month)}</td>
                          <td>{row.model ?? "–"}</td>
                          <td className="num">{row.calls}</td>
                          <td className="num">{row.items_found}</td>
                          <td className="num">${Number(row.total_usd).toFixed(4)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )
          }
        </AsyncBlock>
      </Card>
    </>
  );
}
