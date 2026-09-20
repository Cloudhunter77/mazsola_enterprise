import { type FormEvent, useState } from "react";

import { api } from "../lib/api";
import { AsyncBlock, Card, useAsync } from "../components/ui";
import { PLACE_KINDS } from "../lib/format";

/** Rooms, cupboards, boxes - the tree that answers "where is it?". */
export default function Places() {
  const places = useAsync(() => api.places(), []);
  const [error, setError] = useState<string | null>(null);

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError(null);
    try {
      await api.createPlace({
        name: String(form.get("name")),
        kind: String(form.get("kind")),
        parent_id: form.get("parent_id") || null,
      });
      event.currentTarget.reset();
      places.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function remove(id: string) {
    setError(null);
    try {
      await api.deletePlace(id);
      places.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <>
      <Card title="Új hely">
        <form onSubmit={add}>
          <div className="grid cols-2">
            <label>
              Név
              <input name="name" required placeholder="pl. Fém polc" />
            </label>
            <label>
              Típus
              <select name="kind" defaultValue="room">
                {Object.entries(PLACE_KINDS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <label style={{ gridColumn: "1 / -1" }}>
              Ezen belül
              <select name="parent_id" defaultValue="">
                <option value="">— legfelső szint —</option>
                {(places.data ?? []).map((place) => (
                  <option key={place.id} value={place.id}>{place.path}</option>
                ))}
              </select>
            </label>
          </div>
          {error && <p className="error">{error}</p>}
          <button className="btn primary" style={{ marginTop: 10 }}>Hozzáadás</button>
        </form>
      </Card>

      <Card title="Helyek">
        <AsyncBlock state={places} empty="Még nincs egyetlen hely sem.">
          {(rows) =>
            rows.map((place) => (
              <div className="list-row" key={place.id}>
                <div className="grow">
                  <div className="name">{place.path}</div>
                  <div className="where">
                    {PLACE_KINDS[place.kind] ?? place.kind} · {place.item_count} tétel
                  </div>
                </div>
                <button
                  className="btn danger"
                  onClick={() => remove(place.id)}
                  title="Csak üres hely törölhető"
                >
                  Törlés
                </button>
              </div>
            ))
          }
        </AsyncBlock>
      </Card>
    </>
  );
}
