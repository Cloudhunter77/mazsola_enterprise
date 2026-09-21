import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, type Item } from "../lib/api";
import { Card, Loading, useAsync } from "../components/ui";
import { CONDITIONS, ITEM_STATUS } from "../lib/format";

// A household runs to hundreds of things, so the list pages rather than trying to hold
// all of it at once - and the page is large enough that one press usually ends the
// scrolling rather than starting it.
const PAGE = 100;

/** Everything you own, as far as the app knows: searchable, filterable, exportable. */
export default function Inventory() {
  // The place comes in through the URL as well, so "Hol vannak" on the statistics page
  // can link straight into the garage.
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [place, setPlace] = useState(params.get("hely") ?? "");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("confirmed");

  const [rows, setRows] = useState<Item[] | null>(null);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const places = useAsync(() => api.places(), []);
  const categories = useAsync(() => api.categories(), []);

  // Typing is debounced: a search over a whole household should not fire a request per
  // keystroke, and 250ms is short enough that it still feels like it is keeping up.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(() => {
      api.items({
        q: q || undefined,
        place_id: place || undefined,
        category_id: category || undefined,
        status: status || undefined,
        limit: PAGE,
      })
        .then((result) => {
          if (cancelled) return;
          setRows(result);
          setMore(result.length === PAGE);
          setError(null);
        })
        .catch((err: Error) => !cancelled && setError(err.message))
        .finally(() => !cancelled && setLoading(false));
    }, 250);

    return () => { cancelled = true; clearTimeout(timer); };
  }, [q, place, category, status]);

  async function loadMore() {
    if (!rows) return;
    const next = await api.items({
      q: q || undefined,
      place_id: place || undefined,
      category_id: category || undefined,
      status: status || undefined,
      limit: PAGE,
      offset: rows.length,
    });
    setRows([...rows, ...next]);
    setMore(next.length === PAGE);
  }

  function choosePlace(value: string) {
    setPlace(value);
    // Keep the URL honest, so the view can be shared and the back button works.
    if (value) setParams({ hely: value });
    else setParams({});
  }

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
          placeholder="Keresés – ékezet nélkül is jó"
          value={q}
          onChange={(event) => setQ(event.target.value)}
        />
        <select value={place} onChange={(event) => choosePlace(event.target.value)}>
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

      {error && <p className="empty error">{error}</p>}
      {rows === null ? (
        <Loading />
      ) : rows.length === 0 ? (
        <p className="empty">
          {loading ? "Keresés…" : "Nincs a keresésnek megfelelő tárgy."}
        </p>
      ) : (
          <>
            <p className="card-note" style={{ marginBottom: 8 }}>
              {rows.length}{more ? "+" : ""} tétel ·{" "}
              {rows.reduce((total, row) => total + row.quantity, 0)} darab
              {loading && <> · keresés…</>}
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
                    <Link
                      to={`/targy/${item.id}`}
                      style={{ color: "inherit", textDecoration: "none" }}
                    >
                      {item.name}
                    </Link>
                  </div>
                  <div className="where">
                    {item.place_path ?? "hely nélkül"}
                    {item.category_name ? ` · ${item.category_name}` : ""}
                    {item.brand ? ` · ${item.brand}` : ""}
                    {` · ${CONDITIONS[item.condition] ?? item.condition}`}
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  {item.quantity > 1 && <div className="mono">{item.quantity} db</div>}
                  <div className="where">
                    {item.status !== "confirmed" && (ITEM_STATUS[item.status] ?? item.status)}
                  </div>
                </div>
              </div>
            ))}

            {more && (
              <button className="btn block" onClick={loadMore} style={{ marginTop: 10 }}>
                További {PAGE} tétel
              </button>
            )}
          </>
        )}
    </Card>
  );
}
