/** Kívánságlista: what you mean to buy, not this week but some time.
 *
 *  Grouped by whose it is, the most wanted first. "Listára" puts an item on the shopping
 *  list for the next trip; it stays here until a real purchase is linked to it - from the
 *  receipt's page, or "Megvettük, nincs blokk" here - which also records what it cost and
 *  takes it out of its owner's wishlist savings, if they have a pot for it on Zsebek.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api, type Person, type Wish } from "../lib/api";
import { PRIORITIES, amountOf, dayLabel, owners, plain } from "../lib/budget";
import { ft } from "../lib/format";
import { PurchaseButton } from "./Pockets";
import { AsyncBlock, Card, Empty, useAsync } from "../components/ui";

type Draft = {
  id: string | null; owner_id: string; name: string; priority: number;
  estimated_price: string; link: string; note: string;
};

const blank = (): Draft => ({
  id: null, owner_id: "", name: "", priority: 3, estimated_price: "", link: "", note: "",
});

export default function Wishlist() {
  const [reload, setReload] = useState(0);
  const items = useAsync(() => api.wishlist(), [reload]);
  const users = useAsync(() => api.users(), []);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [showBought, setShowBought] = useState(false);
  const refresh = () => setReload((n) => n + 1);
  const people: Person[] = users.data ?? [];

  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Kívánságlista</h1>

      {draft ? (
        <WishForm draft={draft} setDraft={setDraft} people={people}
                  onDone={() => { setDraft(null); refresh(); }} />
      ) : (
        <button className="btn primary block" style={{ marginBottom: 14 }} onClick={() => setDraft(blank())}>
          + Új tétel
        </button>
      )}

      <AsyncBlock state={items} empty="Még üres a kívánságlista.">
        {(data) => {
          const open = data.filter((w) => !w.bought_on);
          const bought = data.filter((w) => w.bought_on);
          return (
            <>
              {owners(people).map((owner) => {
                const mine = open.filter((w) => w.owner_id === owner.id);
                if (mine.length === 0) return null;
                const total = mine.reduce((sum, w) => sum + Number(w.estimated_price ?? 0), 0);
                return (
                  <Card key={owner.id ?? "kozos"} title={owner.name}
                        note={`${mine.length} tétel · kb. ${ft(total)}`}>
                    {!mine[0].earmark_id && (
                      <p className="muted small" style={{ marginTop: 0 }}>
                        Nincs hozzá gyűjtés: a vásárlás a hónap költése lesz. Gyűjtést a{" "}
                        <Link to="/zsebek">Zsebek</Link> alatt indíthatsz.
                      </p>
                    )}
                    {mine.map((wish) => (
                      <WishRow key={wish.id} wish={wish} onChange={refresh}
                               onEdit={() => {
                                 setDraft({
                                   id: wish.id, owner_id: wish.owner_id ?? "", name: wish.name,
                                   priority: wish.priority, estimated_price: plain(wish.estimated_price),
                                   link: wish.link ?? "", note: wish.note ?? "",
                                 });
                                 window.scrollTo(0, 0);
                               }} />
                    ))}
                  </Card>
                );
              })}
              {open.length === 0 && <Empty>Minden megvéve. 🎉</Empty>}

              {bought.length > 0 && (
                <Card title="Megvéve" action={
                  <button className="btn" onClick={() => setShowBought(!showBought)}>
                    {showBought ? "Elrejtés" : `${bought.length} tétel`}
                  </button>
                }>
                  {showBought && bought.map((wish) => (
                    <div key={wish.id} className="occ-row">
                      <span>
                        {wish.name}
                        <span className="muted small"> · {dayLabel(wish.bought_on as string)}</span>
                      </span>
                      <span className="occ-actions">
                        {wish.receipt_ids[0] ? (
                          <Link className="mono" to={`/blokkok/${wish.receipt_ids[0]}`}>{ft(wish.actual_price)}</Link>
                        ) : <span className="mono">{ft(wish.actual_price)}</span>}
                        <button className="btn" onClick={async () => { await api.reopenWish(wish.id); refresh(); }}>
                          Mégsem
                        </button>
                      </span>
                    </div>
                  ))}
                </Card>
              )}
            </>
          );
        }}
      </AsyncBlock>
    </>
  );
}

function WishRow({ wish, onChange, onEdit }: { wish: Wish; onChange: () => void; onEdit: () => void }) {
  const [busy, setBusy] = useState(false);
  // What it is, with ✎ beside the name; what to do about it on one row under that - rather
  // than three buttons wrapping onto a line each.
  return (
    <div className="occ-row" style={{ display: "block" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div>
            {wish.name}
            <span className="tag">{wish.priority_label}</span>
            {wish.on_list && <span className="tag">listán</span>}
          </div>
          <div className="muted small">
            {wish.estimated_price ? `kb. ${ft(wish.estimated_price)}` : "ár nélkül"}
            {wish.link && (
              <> · {/^https?:\/\//.test(wish.link)
                ? <a href={wish.link} target="_blank" rel="noreferrer">link</a>
                : wish.link}</>
            )}
            {wish.note && ` · ${wish.note}`}
          </div>
        </div>
        <button className="btn icon" aria-label="Szerkesztés" onClick={onEdit}>✎</button>
      </div>
      <div className="row" style={{ gap: 8, marginTop: 8 }}>
        {!wish.on_list && (
          <button className="btn" disabled={busy}
                  onClick={async () => { setBusy(true); try { await api.wishToList(wish.id); onChange(); } finally { setBusy(false); } }}>
            🛒 Listára
          </button>
        )}
        <PurchaseButton wishId={wish.id} name={wish.name} onDone={onChange} />
      </div>
    </div>
  );
}

function WishForm({ draft, setDraft, people, onDone }: {
  draft: Draft; setDraft: (d: Draft | null) => void; people: Person[]; onDone: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch });

  async function save() {
    if (!draft.name.trim()) return setError("Mi legyen?");
    const body = {
      owner_id: draft.owner_id || null, name: draft.name.trim(), priority: draft.priority,
      estimated_price: draft.estimated_price.trim() ? amountOf(draft.estimated_price) : null,
      link: draft.link.trim() || null, note: draft.note.trim() || null,
    };
    try {
      if (draft.id) await api.updateWish(draft.id, body);
      else await api.addWish(body);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function remove() {
    if (!draft.id || !window.confirm(`Törlöd: ${draft.name}?`)) return;
    await api.deleteWish(draft.id);
    onDone();
  }

  return (
    <Card title={draft.id ? "Tétel szerkesztése" : "Új tétel"}
          action={<button className="btn" onClick={() => setDraft(null)}>Mégse</button>}>
      <div className="grid cols-2" style={{ gap: 10 }}>
        <label>Mi<input value={draft.name} onChange={(e) => set({ name: e.target.value })} placeholder="pl. Porszívó" autoFocus /></label>
        <label>
          Kié
          <select value={draft.owner_id} onChange={(e) => set({ owner_id: e.target.value })}>
            {owners(people).map((o) => <option key={o.id ?? "kozos"} value={o.id ?? ""}>{o.name}</option>)}
          </select>
        </label>
        <label>
          Prioritás
          <select value={draft.priority} onChange={(e) => set({ priority: Number(e.target.value) })}>
            {[5, 4, 3, 2, 1].map((p) => <option key={p} value={p}>{PRIORITIES[p]}</option>)}
          </select>
        </label>
        <label>Becsült ár (Ft)<input inputMode="decimal" value={draft.estimated_price} onChange={(e) => set({ estimated_price: e.target.value })} /></label>
        <label>Hol / link<input value={draft.link} onChange={(e) => set({ link: e.target.value })} placeholder="bolt vagy https://…" /></label>
        <label>Megjegyzés<input value={draft.note} onChange={(e) => set({ note: e.target.value })} /></label>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn primary" onClick={save}>Mentés</button>
        {draft.id && <button className="btn danger" onClick={remove}>Törlés</button>}
      </div>
    </Card>
  );
}
