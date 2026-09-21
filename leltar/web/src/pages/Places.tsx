import { type FormEvent, useState } from "react";

import { api, type Place } from "../lib/api";
import { AsyncBlock, Card, useAsync } from "../components/ui";
import { PLACE_KINDS } from "../lib/format";

/** Rooms, cupboards, boxes - the tree that answers "where is it?".
 *
 *  Editable in place, because the seeded rooms are a guess at somebody's house and the
 *  first thing anyone does is make them their own: rename "Gyerekszoba" to a child's name,
 *  move a shelf into the garage it is actually in.
 */
export default function Places() {
  const places = useAsync(() => api.places(), []);
  const [error, setError] = useState<string | null>(null);
  // Disabled while the request is in flight: the impatient second press is what turned
  // one mistake into two identical rooms.
  const [adding, setAdding] = useState(false);

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Held in a variable rather than read back after the await: React nulls
    // `event.currentTarget` as soon as the handler's synchronous part returns, so
    // touching it afterwards throws - and the throw landed in the catch below, which
    // reported a place that had in fact just been created as a failure.
    const element = event.currentTarget;
    const form = new FormData(element);

    setError(null);
    setAdding(true);
    try {
      await api.createPlace({
        name: String(form.get("name")).trim(),
        kind: String(form.get("kind")),
        parent_id: form.get("parent_id") || null,
      });
      element.reset();
      places.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAdding(false);
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

  async function patch(id: string, changes: Record<string, unknown>) {
    setError(null);
    try {
      await api.patchPlace(id, changes);
      places.reload();
    } catch (err) {
      // The server refuses a move that would make a place its own ancestor; show that
      // rather than silently leaving the select pointing somewhere it did not go.
      setError((err as Error).message);
      places.reload();
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
          <button className="btn primary" style={{ marginTop: 10 }} disabled={adding}>
            {adding ? "Hozzáadás…" : "Hozzáadás"}
          </button>
        </form>
      </Card>

      <Card title="Helyek">
        <AsyncBlock state={places} empty="Még nincs egyetlen hely sem.">
          {(rows) =>
            rows.map((place) => (
              <Row
                key={place.id}
                place={place}
                places={rows}
                onPatch={patch}
                onRemove={remove}
              />
            ))
          }
        </AsyncBlock>
      </Card>
    </>
  );
}

function Row({
  place, places, onPatch, onRemove,
}: {
  place: Place;
  places: Place[];
  onPatch: (id: string, changes: Record<string, unknown>) => void;
  onRemove: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="list-row" style={{ flexWrap: "wrap" }}>
      <div className="grow">
        <input
          defaultValue={place.name}
          aria-label="A hely neve"
          onBlur={(event) => {
            const name = event.target.value.trim();
            if (name && name !== place.name) onPatch(place.id, { name });
          }}
        />
        <div className="where">
          {/* The path is worth showing for something nested, and is just the name again
              for a top-level place - where it only repeats the box above it. */}
          {place.path !== place.name && <>{place.path} · </>}
          {PLACE_KINDS[place.kind] ?? place.kind} · {place.item_count} tétel
        </div>
      </div>
      <button className="btn" onClick={() => setOpen((value) => !value)}>
        {open ? "Kész" : "Áthelyezés"}
      </button>
      <button
        className="btn danger"
        onClick={() => onRemove(place.id)}
        title="Csak üres hely törölhető"
      >
        Törlés
      </button>

      {open && (
        <div className="grid cols-2" style={{ width: "100%", marginTop: 8 }}>
          <label>
            Ezen belül
            <select
              value={place.parent_id ?? ""}
              onChange={(event) => onPatch(place.id, { parent_id: event.target.value || null })}
            >
              <option value="">— legfelső szint —</option>
              {places
                .filter((candidate) => candidate.id !== place.id)
                .map((candidate) => (
                  <option key={candidate.id} value={candidate.id}>{candidate.path}</option>
                ))}
            </select>
          </label>
          <label>
            Típus
            <select
              value={place.kind}
              onChange={(event) => onPatch(place.id, { kind: event.target.value })}
            >
              {Object.entries(PLACE_KINDS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
        </div>
      )}
    </div>
  );
}
