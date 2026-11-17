/** Zsebek: the Revolut pockets, and what the money in each is for.
 *
 *  Each pocket shows its balance and, inside it, its earmarks: a goal with its progress,
 *  a pocket-funded line like Hobbi, the wishlist's savings, and whatever money nothing has
 *  claimed yet. Money moves here by hand - an extra deposit, a withdrawal, unassigned money
 *  given to a goal - and a goal is closed here once its thing is bought, with its leftover
 *  moved on or released. The monthly transfers come from the meeting instead (D28).
 *
 *  "Revolut szerint" is the other half of the books: type in what the pocket really holds,
 *  and the difference to what the app expects says whether something was missed.
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  api, type Bucket, type Person, type PocketTransfer, type PocketView, type PocketsOverview,
} from "../lib/api";
import { KIND_LABELS, amountOf, dayLabel, monthLabel, ownerName, owners, plain, pocketLabel, todayIso } from "../lib/budget";
import { ft } from "../lib/format";
import { AsyncBlock, Card, useAsync } from "../components/ui";

type GoalDraft = {
  pocket_id: string; name: string; owner_id: string; wishlist: boolean;
  target: string; target_date: string; saved: string;
};

export default function Pockets() {
  const [reload, setReload] = useState(0);
  const data = useAsync(() => api.pocketsOverview(), [reload]);
  const refresh = () => setReload((n) => n + 1);
  const [addingPocket, setAddingPocket] = useState(false);
  const [goal, setGoal] = useState<GoalDraft | null>(null);

  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Zsebek</h1>

      <AsyncBlock state={data}>
        {(overview) => (
          <>
            {overview.pending.length > 0 && (
              <PendingTransfers items={overview.pending} users={overview.users} onChange={refresh} />
            )}

            {goal && (
              <GoalForm draft={goal} setDraft={setGoal} overview={overview}
                        onDone={() => { setGoal(null); refresh(); }} />
            )}

            {overview.pockets.length === 0 && !addingPocket && (
              <Card>
                <p style={{ marginTop: 0 }}>
                  Ami nem mindennapi költés – megtakarítás, cél, hobbi, kirándulás – az a
                  Revolut-zsebekben van. Vedd fel a zsebeket azzal az összeggel, ami ma bennük
                  van; az app innentől vezeti őket.
                </p>
              </Card>
            )}

            {overview.pockets.map((view) => (
              <PocketCard key={view.pocket.id} view={view} overview={overview} onChange={refresh}
                          onNewGoal={(wishlist) => {
                            setGoal({
                              pocket_id: view.pocket.id, name: wishlist ? "Kívánságlista" : "",
                              owner_id: "", wishlist, target: "", target_date: "", saved: "",
                            });
                            window.scrollTo(0, 0);
                          }} />
            ))}

            {addingPocket ? (
              <PocketForm users={overview.users} onDone={() => { setAddingPocket(false); refresh(); }}
                          onCancel={() => setAddingPocket(false)} />
            ) : (
              <button className="btn block" style={{ marginTop: 14 }} onClick={() => setAddingPocket(true)}>
                + Zseb
              </button>
            )}
            <p className="muted small" style={{ textAlign: "center" }}>
              Egy zsebes keretet (pl. Hobbi) a <Link to="/terv">Terv</Link>ben veszel fel, a
              „Zsebből” mezővel.
            </p>
          </>
        )}
      </AsyncBlock>
    </>
  );
}

function PendingTransfers({ items, users, onChange }: {
  items: PocketTransfer[]; users: Person[]; onChange: () => void;
}) {
  return (
    <Card title="Elküldendő átutalások" note="a havi megbeszélésről">
      <TransferChecklist items={items} users={users} onChange={onChange} />
    </Card>
  );
}

/** Planned transfers nobody has ticked as sent yet. Ticking counts the money from today. */
export function TransferChecklist({ items, users, onChange }: {
  items: PocketTransfer[]; users: Person[]; onChange: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  async function done(id: string) {
    setBusy(id);
    try {
      await api.transferDone(id);
      onChange();
    } finally {
      setBusy(null);
    }
  }
  return (
    <div>
      {items.map((t) => (
        <div key={t.id} className="occ-row">
          <div style={{ flex: "1 1 180px" }}>
            <div>
              {t.from_user_id ? ownerName(users, t.from_user_id) : "?"} →{" "}
              {pocketLabel({ name: t.pocket_name, holder_id: t.holder_id }, users)}
            </div>
            <div className="muted small">{t.line_name ?? "nincs hozzárendelve"} · {dayLabel(t.on)} óta vár</div>
          </div>
          <div className="occ-actions">
            <span className="mono">{ft(t.amount)}</span>
            <button className="btn primary" disabled={busy === t.id} onClick={() => done(t.id)}>
              Elküldve ✓
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

function PocketCard({ view, overview, onChange, onNewGoal }: {
  view: PocketView; overview: PocketsOverview; onChange: () => void;
  onNewGoal: (wishlist: boolean) => void;
}) {
  const { pocket } = view;
  const [editing, setEditing] = useState(false);
  const [check, setCheck] = useState("");
  const [error, setError] = useState<string | null>(null);
  const earmarks = view.buckets.filter((b) => b.line_id !== null);
  const unassigned = view.buckets.find((b) => b.line_id === null);

  async function saveCheck() {
    const value = amountOf(check);
    if (value === null) return setError("Írd be, mennyi van most a zsebben.");
    try {
      await api.pocketCheck(pocket.id, value);
      setCheck("");
      setError(null);
      onChange();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (editing) {
    return <PocketForm users={overview.users} pocket={pocket}
                       onDone={() => { setEditing(false); onChange(); }} onCancel={() => setEditing(false)} />;
  }

  return (
    <Card
      title={pocketLabel(pocket, overview.users)}
      note={pocket.active ? undefined : "archivált"}
      action={<button className="btn" aria-label="Zseb szerkesztése" onClick={() => setEditing(true)}>✎</button>}
    >
      <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
        <span className="muted small">Az app szerint most</span>
        <span style={{ fontSize: "1.4rem", fontWeight: 680 }}>{ft(view.closing)}</span>
      </div>
      {view.check && (
        <div className="small" style={{ marginTop: 4 }}>
          Revolut szerint {dayLabel(view.check.checked_on)}: {ft(view.check.balance)}
          {Number(view.check.difference) === 0 ? (
            <span className="muted"> · egyezik ✓</span>
          ) : (
            <span className="neg"> · eltérés {Number(view.check.difference) > 0 ? "+" : ""}{ft(view.check.difference)}</span>
          )}
        </div>
      )}

      <div style={{ marginTop: 12 }}>
        {earmarks.map((bucket) => (
          <BucketRow key={bucket.line_id} bucket={bucket} pocketId={pocket.id} overview={overview}
                     month={overview.month} onChange={onChange} />
        ))}
        {unassigned && (Number(unassigned.closing) !== 0 || earmarks.length === 0) && (
          <BucketRow bucket={unassigned} pocketId={pocket.id} overview={overview}
                     month={overview.month} onChange={onChange} />
        )}
      </div>

      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn" onClick={() => onNewGoal(false)}>+ Cél</button>
        <button className="btn" onClick={() => onNewGoal(true)}>+ Kívánságlista-gyűjtés</button>
      </div>

      <div className="row" style={{ marginTop: 10, gap: 6 }}>
        <input
          style={{ flex: "1 1 120px", padding: "9px 10px", border: "1px solid var(--border)", borderRadius: 8,
                   background: "var(--surface-raised)", fontSize: 16, minHeight: 44 }}
          inputMode="decimal" placeholder="Revolut szerint most"
          aria-label={`${pocket.name}: mennyi van most a Revolutban`}
          value={check} onChange={(e) => setCheck(e.target.value)}
        />
        <button className="btn" onClick={saveCheck}>Egyeztetés</button>
      </div>
      {error && <p className="error">{error}</p>}
    </Card>
  );
}

function BucketRow({ bucket, pocketId, overview, month, onChange }: {
  bucket: Bucket; pocketId: string; overview: PocketsOverview; month: string; onChange: () => void;
}) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [moveTo, setMoveTo] = useState("");
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isGoal = bucket.target_amount !== null;
  const closing = Number(bucket.closing);
  const target = Number(bucket.target_amount ?? 0);
  const done = isGoal && target > 0 ? Math.min(100, (closing / target) * 100) : 0;
  const others = overview.pockets.flatMap((p) => p.buckets
    .filter((b) => b.line_id && b.line_id !== bucket.line_id && !b.bought_on)
    .map((b) => ({ id: b.line_id as string, label: `${b.name} · ${p.pocket.name}` })));

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      setAmount("");
      onChange();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const value = () => {
    const v = amountOf(amount);
    if (v === null || v <= 0) throw new Error("Adj meg egy összeget.");
    return v;
  };

  return (
    <div className="budget-row">
      <button className="head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span style={{ minWidth: 0 }}>
          {bucket.name}
          {bucket.line_id && bucket.is_wishlist && <span className="tag">Kívánságlista</span>}
          {bucket.line_id && !bucket.is_wishlist && isGoal && <span className="tag">Cél</span>}
          {bucket.line_id && !isGoal && !bucket.is_wishlist && bucket.kind && <span className="tag">{KIND_LABELS[bucket.kind]}</span>}
          {bucket.bought_on && <span className="tag">megvéve</span>}
          {bucket.owner_id && <span className="muted small"> · {ownerName(overview.users, bucket.owner_id)}</span>}
        </span>
        <span className="figures">
          {ft(bucket.closing)}
          {isGoal && <span className="muted"> / {ft(bucket.target_amount)}</span>}
        </span>
      </button>
      {isGoal && (
        <>
          <div className="meter" aria-hidden><span style={{ width: `${done}%` }} /></div>
          <div className="small muted" style={{ marginTop: 4 }}>
            {bucket.target_date ? `${dayLabel(bucket.target_date)}-ig` : "határidő nélkül"}
            {bucket.suggestion !== null && !bucket.bought_on && ` · javasolt: ${ft(bucket.suggestion)}/hó`}
            {Number(bucket.plan) > 0 && ` · ${monthLabel(month).toLowerCase()}i terv: ${ft(bucket.plan)}`}
          </div>
        </>
      )}
      {!isGoal && bucket.line_id && Number(bucket.plan) > 0 && (
        <div className="small muted" style={{ marginTop: 4 }}>
          {monthLabel(month).toLowerCase()}i befizetés: {ft(bucket.plan)}
        </div>
      )}

      {open && (
        <div style={{ marginTop: 10 }}>
          <div className="small muted">
            Ebben az időszakban: {ft(bucket.opening)} + {ft(bucket.money_in)} − {ft(bucket.money_out)}
          </div>
          {bucket.receipts.length > 0 && (
            <ul className="pieces">
              {bucket.receipts.map((piece, i) => (
                <li key={`${piece.receipt_id}-${i}`}>
                  <Link to={`/blokkok/${piece.receipt_id}`}>{dayLabel(piece.day)} · {piece.merchant ?? "?"}</Link>
                  <span className="mono">{ft(piece.amount)}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="occ-actions" style={{ marginTop: 8 }}>
            <input inputMode="decimal" placeholder="összeg" aria-label="Összeg"
                   value={amount} onChange={(e) => setAmount(e.target.value)} />
            <button className="btn" onClick={() => run(() => api.pocketTransfer({
              pocket_id: pocketId, line_id: bucket.line_id, amount: value(),
            }))}>+ Befizetés</button>
            <button className="btn" onClick={() => run(() => api.pocketTransfer({
              pocket_id: pocketId, line_id: bucket.line_id, amount: -value(),
            }))}>− Kivét</button>
          </div>
          {others.length > 0 && (
            <div className="occ-actions" style={{ marginTop: 8 }}>
              <select value={moveTo} onChange={(e) => setMoveTo(e.target.value)} aria-label="Áthelyezés ide"
                      style={{ flex: "1 1 160px", minHeight: 44, borderRadius: 8, padding: "0 8px" }}>
                <option value="">Áthelyezés ide…</option>
                {others.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
              </select>
              <button className="btn" disabled={!moveTo} onClick={() => run(() => api.pocketMove({
                pocket_id: pocketId, from_line_id: bucket.line_id, to_line_id: moveTo, amount: value(),
              }))}>Áthelyezés</button>
            </div>
          )}

          {bucket.line_id && (isGoal || bucket.is_wishlist) && !bucket.bought_on && (
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn" title="Nyisd meg a blokkot, és ott jelöld, melyik sor volt ez"
                      onClick={() => navigate("/blokkok")}>
                Megvettük – blokkból
              </button>
              <PurchaseButton earmarkId={bucket.line_id} name={bucket.name} onDone={onChange} />
              {isGoal && <button className="btn" onClick={() => setFinishing(!finishing)}>Lezárás…</button>}
            </div>
          )}
          {finishing && bucket.line_id && (
            <FinishGoal bucket={bucket} others={others} onDone={onChange} />
          )}
          {error && <p className="error">{error}</p>}
        </div>
      )}
    </div>
  );
}

/** "Megvettük, nincs blokk": what it cost and when, typed in as a one-line receipt. */
export function PurchaseButton({ earmarkId, wishId, name, onDone }: {
  earmarkId?: string; wishId?: string; name: string; onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [price, setPrice] = useState("");
  const [day, setDay] = useState(todayIso());
  const [shop, setShop] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function save() {
    const value = amountOf(price);
    if (value === null || value <= 0) return setError("Mennyibe került?");
    try {
      await api.purchase({
        earmark_id: earmarkId ?? null, wishlist_item_id: wishId ?? null, name,
        price: value, on: day, merchant_name: shop.trim() || null,
      });
      setOpen(false);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (!open) return <button className="btn" onClick={() => setOpen(true)}>Megvettük – nincs blokk</button>;
  return (
    <div className="grid cols-2" style={{ gap: 8, width: "100%", marginTop: 8 }}>
      <label>Ár (Ft)<input inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} autoFocus /></label>
      <label>Mikor<input type="date" value={day} max={todayIso()} onChange={(e) => setDay(e.target.value)} /></label>
      <label>Hol (nem kötelező)<input value={shop} onChange={(e) => setShop(e.target.value)} /></label>
      <div className="row" style={{ alignItems: "flex-end" }}>
        <button className="btn primary" onClick={save}>Rögzítés</button>
        <button className="btn" onClick={() => setOpen(false)}>Mégse</button>
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

function FinishGoal({ bucket, others, onDone }: {
  bucket: Bucket; others: { id: string; label: string }[]; onDone: () => void;
}) {
  const [target, setTarget] = useState("");
  const [error, setError] = useState<string | null>(null);
  const leftover = Number(bucket.closing);

  async function finish(release: boolean) {
    try {
      await api.goalBought(bucket.line_id as string, {
        move_to_line_id: release ? null : target || null, release,
      });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div style={{ marginTop: 8, padding: 10, border: "1px solid var(--border)", borderRadius: 8 }}>
      <p style={{ marginTop: 0 }}>
        A cél lezárul, és többé nem tervez befizetést.
        {leftover > 0 ? ` Maradt benne ${ft(leftover)}: hová kerüljön?` : ""}
      </p>
      {leftover > 0 ? (
        <>
          <select value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Maradék helye"
                  style={{ width: "100%", minHeight: 44, borderRadius: 8, marginBottom: 8 }}>
            <option value="">A zsebben marad, hozzárendelés nélkül</option>
            {others.map((o) => <option key={o.id} value={o.id}>Áthelyezés: {o.label}</option>)}
          </select>
          <div className="row">
            <button className="btn primary" onClick={() => finish(false)}>Lezárás</button>
            <button className="btn" onClick={() => finish(true)}>Lezárás, maradék vissza a főszámlára</button>
          </div>
        </>
      ) : (
        <button className="btn primary" onClick={() => finish(false)}>Lezárás</button>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

function PocketForm({ users, pocket, onDone, onCancel }: {
  users: Person[];
  pocket?: { id: string; name: string; holder_id: string | null; opening_balance: string; opened_on: string; active: boolean };
  onDone: () => void; onCancel: () => void;
}) {
  const [name, setName] = useState(pocket?.name ?? "");
  const [holder, setHolder] = useState(pocket?.holder_id ?? users[0]?.id ?? "");
  const [opening, setOpening] = useState(pocket ? plain(pocket.opening_balance) : "");
  const [openedOn, setOpenedOn] = useState(pocket?.opened_on ?? todayIso());
  const [error, setError] = useState<string | null>(null);

  async function save(active = pocket?.active ?? true) {
    if (!name.trim()) return setError("Adj nevet a zsebnek.");
    const body = {
      name: name.trim(), holder_id: holder || null,
      opening_balance: amountOf(opening) ?? 0, opened_on: openedOn, active,
    };
    try {
      if (pocket) await api.updatePocket(pocket.id, body);
      else await api.createPocket(body);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <Card title={pocket ? "Zseb szerkesztése" : "Új zseb"} action={<button className="btn" onClick={onCancel}>Mégse</button>}>
      <div className="grid cols-2" style={{ gap: 10 }}>
        <label>Név<input value={name} onChange={(e) => setName(e.target.value)} placeholder="pl. Hobby/projektek" autoFocus /></label>
        <label>
          Kinek a Revolutjában
          <select value={holder} onChange={(e) => setHolder(e.target.value)}>
            {users.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
          </select>
        </label>
        <label>Mennyi van benne (Ft)<input inputMode="decimal" value={opening} onChange={(e) => setOpening(e.target.value)} placeholder="0" /></label>
        <label>Ekkor<input type="date" value={openedOn} onChange={(e) => setOpenedOn(e.target.value)} /></label>
      </div>
      <p className="muted small">
        Az app ettől a naptól vezeti a zsebet: ami előtte történt, az már benne van ebben az
        összegben.
      </p>
      {error && <p className="error">{error}</p>}
      <div className="row">
        <button className="btn primary" onClick={() => save()}>Mentés</button>
        {pocket && (
          <button className="btn" onClick={() => save(!pocket.active)}>
            {pocket.active ? "Archiválás" : "Visszaállítás"}
          </button>
        )}
      </div>
    </Card>
  );
}

function GoalForm({ draft, setDraft, overview, onDone }: {
  draft: GoalDraft; setDraft: (d: GoalDraft | null) => void; overview: PocketsOverview; onDone: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const set = (patch: Partial<GoalDraft>) => setDraft({ ...draft, ...patch });
  const pocket = overview.pockets.find((p) => p.pocket.id === draft.pocket_id);
  const free = Number(pocket?.buckets.find((b) => b.line_id === null)?.closing ?? 0);

  async function save() {
    if (!draft.name.trim()) return setError("Adj nevet.");
    const target = amountOf(draft.target);
    const saved = amountOf(draft.saved);
    try {
      await api.createLine({
        name: draft.name.trim(), owner_id: draft.owner_id || null, kind: "celalap",
        category_ids: [], pocket_id: draft.pocket_id, is_wishlist: draft.wishlist,
        target_amount: draft.wishlist ? null : target, target_date: draft.wishlist ? null : draft.target_date || null,
        saved_amount: saved && saved > 0 ? saved : null, from_month: overview.month,
      });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <Card title={draft.wishlist ? "Kívánságlista-gyűjtés" : "Új cél"}
          note={pocket ? `zseb: ${pocket.pocket.name}` : undefined}
          action={<button className="btn" onClick={() => setDraft(null)}>Mégse</button>}>
      <div className="grid cols-2" style={{ gap: 10 }}>
        <label>Név<input value={draft.name} onChange={(e) => set({ name: e.target.value })} placeholder="pl. Kanapé" autoFocus /></label>
        <label>
          Kié
          <select value={draft.owner_id} onChange={(e) => set({ owner_id: e.target.value })}>
            {owners(overview.users).map((o) => <option key={o.id ?? "kozos"} value={o.id ?? ""}>{o.name}</option>)}
          </select>
        </label>
        {!draft.wishlist && (
          <>
            <label>Célösszeg (Ft)<input inputMode="decimal" value={draft.target} onChange={(e) => set({ target: e.target.value })} /></label>
            <label>Céldátum<input type="date" value={draft.target_date} onChange={(e) => set({ target_date: e.target.value })} /></label>
          </>
        )}
        <label>
          Már félretéve rá (Ft)
          <input inputMode="decimal" value={draft.saved} onChange={(e) => set({ saved: e.target.value })}
                 placeholder={free > 0 ? `max ${plain(free)}` : "0"} />
        </label>
      </div>
      <p className="muted small">
        {draft.wishlist
          ? "Ebből a gyűjtésből fizetitek a kívánságlista tételeit. A havi befizetést a Tervben adod meg."
          : "A havi befizetés a javasolt összeggel indul: ami hiányzik, elosztva a céldátumig. A Tervben átírhatod."}
        {" "}A „már félretéve” a zseb hozzá nem rendelt pénzéből jön.
      </p>
      {error && <p className="error">{error}</p>}
      <button className="btn primary" onClick={save}>Mentés</button>
    </Card>
  );
}

