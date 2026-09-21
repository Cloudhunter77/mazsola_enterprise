import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, type Category, type Item, type Place } from "../lib/api";
import { Card, Loading } from "../components/ui";
import { CONDITIONS, PHOTO_STATUS, REVIEW_REASONS, photoTitle } from "../lib/format";

/** One photograph and its guesses: the screen the whole app exists for.
 *
 *  Every draft is a name you can accept as it stands, tap an alternative for, or retype.
 *  Nothing here saves silently - a draft becomes part of the inventory only when you say
 *  so, which is what makes the rest of the app's numbers mean anything.
 */
export default function PhotoReview() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [photo, setPhoto] = useState<Awaited<ReturnType<typeof api.photo>> | null>(null);
  const [places, setPlaces] = useState<Place[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [detail, placeRows, categoryRows] = await Promise.all([
        api.photo(id),
        api.places(),
        api.categories(),
      ]);
      setPhoto(detail);
      setPlaces(placeRows);
      setCategories(categoryRows);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // While the worker is still reading it, the page waits with you.
  useEffect(() => {
    if (!photo || (photo.status !== "pending" && photo.status !== "processing")) return;
    const timer = setTimeout(load, 3000);
    return () => clearTimeout(timer);
  }, [photo, load]);

  if (error) return <p className="empty error">{error}</p>;
  if (!photo) return <Loading />;

  const drafts = photo.items.filter((item) => item.status === "draft");

  async function confirmAll() {
    setBusy(true);
    try {
      await api.confirmPhotoItems(id);
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function reprocess() {
    setBusy(true);
    try {
      setPhoto(await api.reprocessPhoto(id));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!confirm("Törlöd ezt a fényképet? A már megerősített tételek megmaradnak.")) return;
    await api.deletePhoto(id);
    navigate("/ellenorzes");
  }

  return (
    <>
      <div className="page-actions row" style={{ marginBottom: 12 }}>
        <h1>
          {photoTitle(
            photo.items.map((item) => item.name),
            photo.items.length,
            photo.scene,
          )}
        </h1>
        <span className="badge">{PHOTO_STATUS[photo.status] ?? photo.status}</span>
      </div>

      <div className="grid cols-2">
        <div>
          <div className="photo-frame">
            <img src={api.photoImageUrl(id)} alt={photo.scene ?? "Fénykép"} />
            {/* The scene is context under the picture now, not the heading. */}
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn" onClick={reprocess} disabled={busy}>Újraolvasás</button>
            <button className="btn danger" onClick={remove}>Törlés</button>
          </div>
          {(photo.review_reasons ?? []).length > 0 && (
            <div className="draft-meta" style={{ marginTop: 10 }}>
              {(photo.review_reasons ?? []).map((reason) => (
                <span className="reason" key={reason}>{REVIEW_REASONS[reason] ?? reason}</span>
              ))}
            </div>
          )}
          {photo.error && <p className="error" style={{ marginTop: 10 }}>{photo.error}</p>}
        </div>

        <div>
          <Card
            title={drafts.length > 0 ? `${drafts.length} javaslat` : "Nincs nyitott javaslat"}
            action={
              drafts.length > 0 ? (
                <button className="btn primary" onClick={confirmAll} disabled={busy}>
                  Mind rendben
                </button>
              ) : undefined
            }
          >
            {photo.status === "pending" || photo.status === "processing" ? (
              <Loading label="A gép még nézi…" />
            ) : photo.items.length === 0 ? (
              <p className="empty">Ezen a képen nem talált megnevezhető tárgyat.</p>
            ) : (
              photo.items.map((item) => (
                <Draft
                  key={item.id}
                  item={item}
                  places={places}
                  categories={categories}
                  onChanged={load}
                />
              ))
            )}
          </Card>
        </div>
      </div>
    </>
  );
}

function Draft({
  item, places, categories, onChanged,
}: {
  item: Item; places: Place[]; categories: Category[]; onChanged: () => void;
}) {
  const [name, setName] = useState(item.name);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => setName(item.name), [item.name]);

  async function save(patch: Record<string, unknown>) {
    setBusy(true);
    try {
      await api.patchItem(item.id, patch);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function accept() {
    setBusy(true);
    try {
      // The name is saved first when it was retyped, so confirming never loses an edit
      // that was typed but not yet blurred.
      if (name.trim() && name !== item.name) await api.patchItem(item.id, { name: name.trim() });
      await api.confirmItem(item.id);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  const reasons = item.review_reasons ?? [];
  const alternatives = item.alternatives ?? [];

  return (
    <div className={`draft ${item.status}`}>
      <div className="row" style={{ gap: 10, alignItems: "flex-start", marginBottom: 8 }}>
        {/* The crop the model's box produced. Showing it here is what makes a box in the
            wrong place obvious now, rather than a mystery picture in the inventory. */}
        <img className="thumb" src={api.itemImageUrl(item.id)} alt="" loading="lazy" />
        <span className="muted" style={{ fontSize: "0.78rem" }}>
          {item.suggested_name && item.suggested_name !== item.name
            ? `a gép szerint: ${item.suggested_name}`
            : ""}
        </span>
      </div>
      <div className="draft-head">
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          onBlur={() => name.trim() && name !== item.name && save({ name: name.trim() })}
          aria-label="A tárgy neve"
        />
        {item.status === "draft" ? (
          <>
            <button className="btn primary" onClick={accept} disabled={busy}>Rendben</button>
            <button
              className="btn"
              onClick={() => api.rejectItem(item.id).then(onChanged)}
              title="Ez nem olyasmi, amit leltárba akarok venni"
            >
              Nem kell
            </button>
          </>
        ) : (
          <span className={item.status === "confirmed" ? "badge good" : "badge"}>
            {item.status === "confirmed" ? "Megerősítve" : "Elvetve"}
          </span>
        )}
      </div>

      {alternatives.length > 0 && item.status === "draft" && (
        <div className="alts">
          {alternatives.map((alternative) => (
            <button key={alternative} onClick={() => save({ name: alternative })}>
              {alternative}
            </button>
          ))}
        </div>
      )}

      <div className="draft-meta">
        <span>{item.category_name ?? "Besorolatlan"}</span>
        {item.place_path && <><span>·</span><span>{item.place_path}</span></>}
        {item.quantity > 1 && <><span>·</span><span>{item.quantity} db</span></>}
        {item.brand && <><span>·</span><span>{item.brand} {item.product_model ?? ""}</span></>}
        {item.confidence != null && (
          <><span>·</span><span>biztonság {Math.round(item.confidence * 100)}%</span></>
        )}
        <button
          className="btn"
          style={{ minHeight: 28, padding: "2px 10px", fontSize: "0.78rem" }}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? "Kevesebb" : "Részletek"}
        </button>
      </div>

      {reasons.length > 0 && (
        <div className="draft-meta">
          {reasons.map((reason) => (
            <span className="reason" key={reason}>{REVIEW_REASONS[reason] ?? reason}</span>
          ))}
        </div>
      )}

      {open && (
        <div className="grid cols-2" style={{ marginTop: 10 }}>
          <label>
            Hely
            <select
              value={item.place_id ?? ""}
              onChange={(event) => save({ place_id: event.target.value || null })}
            >
              <option value="">— nincs —</option>
              {places.map((place) => (
                <option key={place.id} value={place.id}>{place.path}</option>
              ))}
            </select>
          </label>
          <label>
            Kategória
            <select
              value={item.category_id ?? ""}
              onChange={(event) => save({ category_id: event.target.value || null })}
            >
              <option value="">— nincs —</option>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.icon} {category.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Állapot
            <select
              value={item.condition}
              onChange={(event) => save({ condition: event.target.value })}
            >
              {Object.entries(CONDITIONS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <label>
            Darab
            <input
              type="number"
              min={1}
              defaultValue={item.quantity}
              onBlur={(event) => save({ quantity: Number(event.target.value) || 1 })}
            />
          </label>
          <label>
            Érték (Ft, ha fontos)
            <input
              type="number"
              defaultValue={item.value ?? ""}
              onBlur={(event) => save({ value: event.target.value || null })}
            />
          </label>
          <label style={{ gridColumn: "1 / -1" }}>
            Megjegyzés
            <input
              defaultValue={item.notes ?? ""}
              onBlur={(event) => save({ notes: event.target.value || null })}
            />
          </label>
        </div>
      )}
    </div>
  );
}
