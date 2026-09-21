import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, type Category, type Item, type ItemImage, type Place } from "../lib/api";
import { Card, Loading } from "../components/ui";
import { CONDITIONS, ITEM_STATUS, date, ft } from "../lib/format";

/** One thing: its pictures, its details, and a way to add more of both.
 *
 *  The second pass an inventory actually needs. The first pass is the model naming what it
 *  saw; this is where a thing acquires the photographs that make it identifiable later -
 *  the serial plate, the damage, the thing out of its case - and the facts no photograph
 *  carries, like what you paid and when.
 */
export default function ItemPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState<Item | null>(null);
  const [images, setImages] = useState<ItemImage[]>([]);
  const [shown, setShown] = useState<string | null>(null);
  const [places, setPlaces] = useState<Place[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const [row, gallery, placeRows, categoryRows] = await Promise.all([
        api.item(id),
        api.itemImages(id),
        api.places(),
        api.categories(),
      ]);
      setItem(row);
      setImages(gallery);
      setShown((current) => current ?? gallery[0]?.id ?? null);
      setPlaces(placeRows);
      setCategories(categoryRows);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  if (error) return <p className="empty error">{error}</p>;
  if (!item) return <Loading />;

  async function save(patch: Record<string, unknown>) {
    setBusy(true);
    try {
      setItem(await api.patchItem(id, patch));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function addPhoto(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      for (const file of Array.from(files)) await api.addItemImage(id, file);
      const gallery = await api.itemImages(id);
      setImages(gallery);
      setShown(gallery[0]?.id ?? null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function removePhoto(imageId: string) {
    if (!confirm("Törlöd ezt a képet?")) return;
    await api.deleteItemImage(imageId);
    const gallery = await api.itemImages(id);
    setImages(gallery);
    setShown(gallery[0]?.id ?? null);
  }

  async function remove() {
    if (!confirm(`Törlöd: ${item?.name}? A képei is törlődnek.`)) return;
    await api.deleteItem(id);
    navigate("/leltar");
  }

  const current = images.find((image) => image.id === shown) ?? images[0];

  return (
    <>
      <div className="page-actions row" style={{ marginBottom: 12 }}>
        <h1>{item.name}</h1>
        {item.status !== "confirmed" && (
          <span className="badge">{ITEM_STATUS[item.status] ?? item.status}</span>
        )}
      </div>

      <div className="grid cols-2">
        <Card title="Képek" note={images.length === 0 ? "még nincs kép" : `${images.length} db`}>
          <div className="gallery">
            {current ? (
              <img className="main" src={`/api/items/${id}/image?v=${current.id}`} alt={item.name} />
            ) : (
              <p className="empty">Ehhez a tárgyhoz még nincs fénykép.</p>
            )}

            {images.length > 1 && (
              <div className="strip">
                {images.map((image) => (
                  <img
                    key={image.id}
                    className={image.id === current?.id ? "current" : ""}
                    src={`/api/items/${id}/image?v=${image.id}`}
                    alt=""
                    onClick={() => setShown(image.id)}
                  />
                ))}
              </div>
            )}

            <div className="row">
              <label className="btn">
                📷 Kép hozzáadása
                <input
                  ref={fileInput}
                  type="file"
                  accept="image/*"
                  multiple
                  style={{ display: "none" }}
                  onChange={(event) => addPhoto(event.target.files)}
                />
              </label>
              {current && !current.is_primary && (
                <button
                  className="btn"
                  onClick={() => api.setPrimaryImage(current.id).then(load)}
                >
                  Ez legyen a fő kép
                </button>
              )}
              {current && (
                <button className="btn danger" onClick={() => removePhoto(current.id)}>
                  Kép törlése
                </button>
              )}
            </div>
            {current?.kind === "crop" && (
              <p className="card-note">
                Ez a kép a fényképből kivágva készült. Ha nem a megfelelő részt mutatja,
                fényképezd le külön a tárgyat és add hozzá.
              </p>
            )}
          </div>
        </Card>

        <Card title="Adatok" note={busy ? "mentés…" : undefined}>
          <label className="field">
            Név
            <input
              defaultValue={item.name}
              onBlur={(event) =>
                event.target.value.trim() &&
                event.target.value !== item.name &&
                save({ name: event.target.value.trim() })
              }
            />
          </label>

          <div className="grid cols-2">
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
              Márka
              <input
                defaultValue={item.brand ?? ""}
                onBlur={(event) => save({ brand: event.target.value || null })}
              />
            </label>
            <label>
              Típus
              <input
                defaultValue={item.product_model ?? ""}
                onBlur={(event) => save({ product_model: event.target.value || null })}
              />
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
            <label>
              Sorozatszám
              <input
                defaultValue={item.serial_number ?? ""}
                onBlur={(event) => save({ serial_number: event.target.value || null })}
              />
            </label>
            <label>
              Beszerzés
              <input
                type="date"
                defaultValue={item.acquired_on ?? ""}
                onBlur={(event) => save({ acquired_on: event.target.value || null })}
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

          <p className="card-note" style={{ marginTop: 10 }}>
            {item.place_path ?? "hely nélkül"}
            {item.suggested_name && item.suggested_name !== item.name && (
              <> · a gép szerint: {item.suggested_name}</>
            )}
            {item.value && <> · {ft(item.value)}</>}
            {item.acquired_on && <> · beszerezve: {date(item.acquired_on)}</>}
          </p>

          <div className="row" style={{ marginTop: 10 }}>
            {item.status !== "confirmed" && (
              <button
                className="btn primary"
                onClick={() => api.confirmItem(id).then(setItem)}
              >
                Megerősítés
              </button>
            )}
            {item.photo_id && (
              <a className="btn" href={`/fenykep/${item.photo_id}`}>Az eredeti fénykép</a>
            )}
            <button className="btn danger" onClick={remove}>Törlés</button>
          </div>
        </Card>
      </div>
    </>
  );
}
