import { type FormEvent, useState } from "react";

import { api } from "../lib/api";
import { Card, useAsync } from "../components/ui";
import { CONDITIONS } from "../lib/format";

/** Type in something that was never photographed.
 *
 *  A leltár with holes in it is worse than useless for insurance, and some things cannot
 *  be photographed usefully - what is in the loft, what is lent out, what lives in a case.
 */
export default function Manual() {
  const places = useAsync(() => api.places(), []);
  const categories = useAsync(() => api.categories(), []);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Held before the await; see the note in Places.tsx - React nulls `currentTarget`
    // once the handler returns, and reading it afterwards throws.
    const element = event.currentTarget;
    const form = new FormData(element);
    const value = (key: string) => {
      const raw = form.get(key);
      return raw === null || raw === "" ? null : String(raw);
    };

    setBusy(true);
    setError(null);
    try {
      const item = await api.createItem({
        name: value("name"),
        place_id: value("place_id"),
        category_id: value("category_id"),
        brand: value("brand"),
        product_model: value("product_model"),
        condition: value("condition") ?? "unknown",
        quantity: Number(value("quantity") ?? 1) || 1,
        serial_number: value("serial_number"),
        value: value("value"),
        acquired_on: value("acquired_on"),
        notes: value("notes"),
      });
      setSaved(item.name);
      element.reset();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Kézi rögzítés" note="Amit nem fényképeztél le">
      <form onSubmit={submit}>
        <label className="field">
          Név
          <input name="name" required placeholder="pl. Makita akkus fúró" />
        </label>

        <div className="grid cols-2">
          <label>
            Hely
            <select name="place_id" defaultValue="">
              <option value="">— nincs —</option>
              {(places.data ?? []).map((place) => (
                <option key={place.id} value={place.id}>{place.path}</option>
              ))}
            </select>
          </label>
          <label>
            Kategória
            <select name="category_id" defaultValue="">
              <option value="">— nincs —</option>
              {(categories.data ?? []).map((category) => (
                <option key={category.id} value={category.id}>
                  {category.icon} {category.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Márka
            <input name="brand" />
          </label>
          <label>
            Típus
            <input name="product_model" />
          </label>
          <label>
            Állapot
            <select name="condition" defaultValue="unknown">
              {Object.entries(CONDITIONS).map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
          </label>
          <label>
            Darab
            <input name="quantity" type="number" min={1} defaultValue={1} />
          </label>
          <label>
            Érték (Ft, ha fontos)
            <input name="value" type="number" />
          </label>
          <label>
            Sorozatszám
            <input name="serial_number" />
          </label>
          <label>
            Beszerzés dátuma
            <input name="acquired_on" type="date" />
          </label>
          <label style={{ gridColumn: "1 / -1" }}>
            Megjegyzés
            <input name="notes" />
          </label>
        </div>

        {error && <p className="error">{error}</p>}
        {saved && <p className="muted">Rögzítve: {saved}</p>}

        <button className="btn primary block" disabled={busy} style={{ marginTop: 12 }}>
          {busy ? "Mentés…" : "Hozzáadás a leltárhoz"}
        </button>
      </form>
    </Card>
  );
}
