import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { AsyncBlock, Card, Tile, useAsync } from "../components/ui";
import { dateTime, pct } from "../lib/format";

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
              label="Tétel a leltárban"
              value={data.items}
              sub={`${data.copies} darab összesen`}
            />
            <Tile
              label="Képpel"
              value={data.items === 0 ? "–" : pct(data.with_picture / data.items)}
              // The point of the pictures is recognising a row without reading it, so how
              // much of the catalogue you could actually recognise is worth watching.
              sub={`${data.with_picture} tételt ismersz fel ránézésre`}
            />
            <Tile
              label="Helyek"
              value={data.places_used}
              sub={`${data.categories_used} kategória`}
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

      <Card title="Hol vannak" note="a tételek száma helyenként">
        <AsyncBlock state={places} empty="Még nincs megerősített tétel.">
          {(rows) => {
            const max = Math.max(...rows.map((row) => row.items), 1);
            return rows.map((row) => (
              <div className="list-row" key={row.place_path}>
                <div className="grow">
                  <div className="name">
                    {row.place_id ? (
                      <Link to={`/leltar?hely=${row.place_id}`} style={{ color: "inherit" }}>
                        {row.place_path}
                      </Link>
                    ) : (
                      row.place_path
                    )}
                  </div>
                  <div className="bar" style={{ marginTop: 6 }}>
                    <span style={{ width: `${(row.items / max) * 100}%` }} />
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div className="mono">{row.items}</div>
                  <div className="where">{row.copies} db</div>
                </div>
              </div>
            ));
          }}
        </AsyncBlock>
      </Card>

      <Card title="Mi van" note="a tételek száma kategóriánként">
        <AsyncBlock state={categories} empty="Még nincs megerősített tétel.">
          {(rows) =>
            rows.map((row) => (
              <div className="list-row" key={row.category_name}>
                <div className="grow">
                  <div className="name">{row.icon ?? "📦"} {row.category_name}</div>
                  <div className="where">{pct(row.share)} · {row.copies} db</div>
                </div>
                <div className="mono">{row.items}</div>
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
