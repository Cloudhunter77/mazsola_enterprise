/** The shopping list.
 *
 *  Different from every other screen here. The rest of the app records what already
 *  happened and has to be exactly right because statistics depend on it. This is about the
 *  next half hour, and its only job is to be recognisable to you while you stand in an
 *  aisle holding a basket.
 *
 *  So an item does not have to be anything in particular. A product you track, a name you
 *  typed, or a photograph of a thing you want more of - and the photograph is a complete
 *  entry, not a placeholder waiting to become one. You recognise your own shopping
 *  instantly; a name would add nothing.
 */

import { useRef, useState } from "react";

import { api, type ShoppingItem } from "../lib/api";
import { AsyncBlock, Card, useAsync, useLive } from "../components/ui";

const READING = new Set(["pending", "processing"]);

export default function Shopping() {
  const [reload, setReload] = useState(0);
  const items = useAsync(() => api.shoppingList(), [reload]);
  const usual = useAsync(() => api.shoppingSuggestions(), [reload]);
  // A photographed item lands as "Felismerés…" and the reading happens on the server
  // afterwards, so without this the entry sat unrecognised until you left and came back.
  // Refreshing on focus also picks up anything added from another phone.
  useLive(items, (rows) => rows.some((row) => READING.has(row.status)));
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const camera = useRef<HTMLInputElement>(null);
  const gallery = useRef<HTMLInputElement>(null);

  const refresh = () => setReload((n) => n + 1);

  async function run(work: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await work();
      refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function addTyped() {
    const name = typed.trim();
    if (!name) return;
    setTyped("");
    await run(() => api.addToList({ raw_name: name }));
  }

  async function send(files: FileList | null) {
    if (!files?.length) return;
    await run(async () => {
      for (const file of Array.from(files)) await api.scanOntoList(file);
    });
  }

  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Bevásárlólista</h1>

      <Card>
        <div className="row" style={{ gap: 8 }}>
          <input
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && addTyped()}
            placeholder="Mi kell? pl. Tej 1l"
            style={{ flex: "3 1 160px" }}
            aria-label="Új tétel"
          />
          <button
            className="btn primary"
            style={{ flex: "1 1 90px" }}
            onClick={addTyped}
            disabled={busy || !typed.trim()}
          >
            Hozzáad
          </button>
        </div>

        <input
          ref={camera}
          type="file"
          accept="image/*"
          capture="environment"
          multiple
          hidden
          onChange={(event) => { send(event.target.files); event.target.value = ""; }}
        />
        <input
          ref={gallery}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={(event) => { send(event.target.files); event.target.value = ""; }}
        />

        <div className="row" style={{ gap: 8, marginTop: 8 }}>
          <button
            className="btn"
            style={{ flex: 1 }}
            onClick={() => camera.current?.click()}
            disabled={busy}
          >
            📷 Lefotózom
          </button>
          <button
            className="btn"
            style={{ flex: 1 }}
            onClick={() => gallery.current?.click()}
            disabled={busy}
          >
            🖼️ Tallózás
          </button>
        </div>
        <p className="muted" style={{ fontSize: "0.82rem", marginBottom: 0 }}>
          Fotózd le, amiből kell még: ha felismeri, termékként kerül fel, ha nem, a kép marad.
        </p>

        {error && <p className="error">{error}</p>}
      </Card>

      <AsyncBlock state={usual} empty="">
        {(rows) =>
          rows.length === 0 ? <></> : (
            <Card title="Amit szoktál venni">
              <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                {rows.map((row) => (
                  <button
                    key={row.product_id}
                    className="btn"
                    disabled={busy}
                    onClick={() => run(() => api.addToList({ product_id: row.product_id }))}
                  >
                    🛒 {row.canonical_name}
                  </button>
                ))}
              </div>
            </Card>
          )
        }
      </AsyncBlock>

      <AsyncBlock state={items} empty="A lista üres.">
        {(rows) => {
          const todo = rows.filter((row) => !row.done);
          const done = rows.filter((row) => row.done);
          return (
            <Card
              title="A lista"
              note={`${todo.length} tétel`}
              action={
                done.length > 0 ? (
                  <button className="btn" onClick={() => run(() => api.clearDone())}>
                    Kipipáltak törlése ({done.length})
                  </button>
                ) : undefined
              }
            >
              {todo.map((item) => (
                <Row key={item.id} item={item} busy={busy} run={run} />
              ))}
              {done.length > 0 && (
                <p className="muted" style={{ fontSize: "0.84rem", marginTop: 16 }}>
                  Megvan
                </p>
              )}
              {done.map((item) => (
                <Row key={item.id} item={item} busy={busy} run={run} />
              ))}
            </Card>
          );
        }}
      </AsyncBlock>
    </>
  );
}

/** One thing to buy. In the shop it is the name you tap, not a 24px box beside it: the
 *  whole label ticks it off. The photo is a link of its own and opens without ticking. */
function Row({
  item,
  busy,
  run,
}: {
  item: ShoppingItem;
  busy: boolean;
  run: (work: () => Promise<unknown>) => Promise<void>;
}) {
  return (
    <div
      className="row"
      style={{
        gap: 8,
        flexWrap: "nowrap",
        borderTop: "1px solid var(--grid)",
        paddingTop: 6,
        marginTop: 6,
        opacity: item.done ? 0.5 : 1,
      }}
    >
      <label className="check" style={{ flex: 1, minWidth: 0, minHeight: 52 }}>
        <input
          type="checkbox"
          checked={item.done}
          disabled={busy}
          onChange={() => run(() => api.updateListItem(item.id, { done: !item.done }))}
        />

        {item.has_photo && (
          <a
            href={api.listItemImageUrl(item.id)}
            target="_blank"
            rel="noreferrer"
            style={{ flex: "0 0 auto" }}
            aria-label="A fotó megnyitása"
          >
            <img
              src={api.listItemImageUrl(item.id)}
              alt=""
              loading="lazy"
              style={{
                width: 48,
                height: 48,
                objectFit: "cover",
                borderRadius: 8,
                background: "var(--grid)",
                display: "block",
              }}
            />
          </a>
        )}

        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{ display: "block", textDecoration: item.done ? "line-through" : undefined }}>
            {item.label}
            {item.quantity && <span className="muted"> · {item.quantity}</span>}
          </span>
          <Status item={item} />
        </span>
      </label>

      <button
        className="btn icon"
        aria-label={`${item.label} törlése`}
        disabled={busy}
        onClick={() => run(() => api.deleteListItem(item.id))}
      >
        🗑
      </button>
    </div>
  );
}

function Status({ item }: { item: ShoppingItem }) {
  if (READING.has(item.status)) {
    return <span className="muted" style={{ display: "block", fontSize: "0.78rem" }}>Felismerés…</span>;
  }
  if (item.product_id) {
    return (
      <span className="muted" style={{ display: "block", fontSize: "0.78rem" }}>
        <span className="badge good">ismert termék</span>
      </span>
    );
  }
  if (item.has_photo && item.raw_name) {
    // Read, but not confidently enough to attach to a product - so the name is a hint and
    // the photo is still what you go by.
    return (
      <span className="muted" style={{ display: "block", fontSize: "0.78rem" }}>
        a kép alapján: {item.raw_name}
      </span>
    );
  }
  if (item.status === "failed") {
    return (
      <span className="muted" style={{ display: "block", fontSize: "0.78rem" }}>
        Nem sikerült felismerni – a kép marad.
      </span>
    );
  }
  return null;
}
