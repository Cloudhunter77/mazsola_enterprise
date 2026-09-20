import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { AsyncBlock, Card, Tile, useAsync } from "../components/ui";
import { dateTime, ft, pct } from "../lib/format";

/** What is in the house, and how well the machine is doing at naming it. */
export default function Dashboard() {
  const summary = useAsync(() => api.summary(), []);
  const places = useAsync(() => api.byPlace(), []);
  const categories = useAsync(() => api.byCategory(), []);
  const accuracy = useAsync(() => api.accuracy(), []);

  return (
    <>
      <AsyncBlock state={summary}>
        {(data) => (
          <div className="grid tiles">
            <Tile
              label="Megerősített tétel"
              value={data.items}
              sub={`${data.copies} darab összesen`}
            />
            <Tile
              label="Becsült érték"
              value={ft(data.total_value)}
              // The share matters: a total built from a third of the inventory is not a
              // household's worth, and the tile should not pretend otherwise.
              sub={`${data.valued_items} tételre van becslés`}
            />
            <Tile label="Nyitott javaslat" value={data.drafts} sub="ellenőrzésre vár" />
            <Tile
              label="Fényképek"
              value={data.photos}
              sub={
                data.photos_pending > 0
                  ? `${data.photos_pending} olvasás alatt`
                  : `${data.photos_needing_review} átnézendő`
              }
            />
          </div>
        )}
      </AsyncBlock>

      <Card title="Helyek szerint">
        <AsyncBlock state={places} empty="Még nincs megerősített tétel.">
          {(rows) => {
            const max = Math.max(...rows.map((row) => Number(row.total_value)), 1);
            return rows.map((row) => (
              <div className="list-row" key={row.place_path}>
                <div className="grow">
                  <div className="name">{row.place_path}</div>
                  <div className="bar" style={{ marginTop: 6 }}>
                    <span style={{ width: `${(Number(row.total_value) / max) * 100}%` }} />
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div className="mono">{ft(row.total_value)}</div>
                  <div className="where">{row.items} tétel</div>
                </div>
              </div>
            ));
          }}
        </AsyncBlock>
      </Card>

      <Card title="Kategóriák szerint">
        <AsyncBlock state={categories} empty="Még nincs megerősített tétel.">
          {(rows) =>
            rows.map((row) => (
              <div className="list-row" key={row.category_name}>
                <div className="grow">
                  <div className="name">{row.icon ?? "📦"} {row.category_name}</div>
                  <div className="where">{row.items} tétel · {pct(row.share)}</div>
                </div>
                <div className="mono">{ft(row.total_value)}</div>
              </div>
            ))
          }
        </AsyncBlock>
      </Card>

      <Card title="Pontosság" note="Mennyire kell javítanod a gépet">
        <AsyncBlock state={accuracy}>
          {(data) =>
            data.confirmed_from_photos === 0 ? (
              <p className="empty">Még nincs fényképből megerősített tétel.</p>
            ) : (
              <div className="grid tiles">
                <Tile
                  label="Változtatás nélkül elfogadva"
                  value={pct(data.keep_rate)}
                  sub={`${data.kept_as_suggested} / ${data.confirmed_from_photos} névből`}
                />
                <Tile label="Átírva" value={data.edited} sub="nevet javítottál" />
                <Tile
                  label="Átlagos biztonság"
                  value={data.mean_confidence == null ? "–" : pct(data.mean_confidence)}
                  sub="amit a gép magáról állított"
                />
              </div>
            )
          }
        </AsyncBlock>
      </Card>

      <AsyncBlock state={summary}>
        {(data) => (
          <p className="card-note" style={{ marginTop: 12 }}>
            Utolsó rögzítés: {dateTime(data.last_added)} · <Link to="/rendszer">Rendszer és költség</Link>
          </p>
        )}
      </AsyncBlock>
    </>
  );
}
