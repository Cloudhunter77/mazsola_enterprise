import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { AsyncBlock, Card, useAsync } from "../components/ui";
import { CONDITIONS, ITEM_STATUS, ft } from "../lib/format";

/** Everything you own, as far as the app knows: searchable, filterable, exportable. */
export default function Inventory() {
  const [q, setQ] = useState("");
  const [place, setPlace] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("confirmed");

  const places = useAsync(() => api.places(), []);
  const categories = useAsync(() => api.categories(), []);
  const items = useAsync(
    () => api.items({ q: q || undefined, place_id: place || undefined,
                      category_id: category || undefined, status: status || undefined,
                      limit: 300 }),
    [q, place, category, status],
  );

  return (
    <Card
      title="Leltár"
      action={
        <span className="row">
          <Link className="btn" to="/kezi">Kézi rögzítés</Link>
          <a className="btn" href={api.exportCsvUrl()}>CSV</a>
        </span>
      }
    >
      <div className="filters">
        <input
          type="search"
          placeholder="Keresés név, márka, sorozatszám szerint…"
          value={q}
          onChange={(event) => setQ(event.target.value)}
        />
        <select value={place} onChange={(event) => setPlace(event.target.value)}>
          <option value="">Minden hely</option>
          {(places.data ?? []).map((row) => (
            <option key={row.id} value={row.id}>{row.path}</option>
          ))}
        </select>
        <select value={category} onChange={(event) => setCategory(event.target.value)}>
          <option value="">Minden kategória</option>
          {(categories.data ?? []).map((row) => (
            <option key={row.id} value={row.id}>{row.icon} {row.name}</option>
          ))}
        </select>
        <select value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="confirmed">Megerősítve</option>
          <option value="draft">Javaslat</option>
          <option value="rejected">Elvetve</option>
          <option value="">Mind</option>
        </select>
      </div>

      <AsyncBlock state={items} empty="Nincs a szűrésnek megfelelő tárgy.">
        {(rows) => (
          <>
            <p className="card-note" style={{ marginBottom: 8 }}>
              {rows.length} tétel ·{" "}
              {ft(rows.reduce(
                (total, row) => total + Number(row.estimated_value ?? 0) * row.quantity, 0,
              ))}
            </p>
            {rows.map((item) => (
              <div className="list-row" key={item.id}>
                {item.image_count > 0 ? (
                  <img className="thumb" src={api.itemImageUrl(item.id)} alt="" loading="lazy" />
                ) : (
                  // A placeholder rather than a missing-image icon: plenty of items are
                  // typed in and will never have a photograph, and a broken icon on every
                  // one of those rows reads as a fault.
                  <span className="thumb empty" aria-hidden>📦</span>
                )}
                <div className="grow">
                  <div className="name">
                    <Link to={`/targy/${item.id}`} style={{ color: "inherit", textDecoration: "none" }}>
                      {item.name}
                    </Link>
                    {item.quantity > 1 && <span className="muted"> ×{item.quantity}</span>}
                  </div>
                  <div className="where">
                    {item.place_path ?? "hely nélkül"}
                    {item.category_name ? ` · ${item.category_name}` : ""}
                    {item.brand ? ` · ${item.brand}` : ""}
                    {` · ${CONDITIONS[item.condition] ?? item.condition}`}
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div className="mono">{ft(item.estimated_value)}</div>
                  <div className="where">
                    {item.status !== "confirmed" && (ITEM_STATUS[item.status] ?? item.status)}
                  </div>
                </div>
              </div>
            ))}
          </>
        )}
      </AsyncBlock>
    </Card>
  );
}
