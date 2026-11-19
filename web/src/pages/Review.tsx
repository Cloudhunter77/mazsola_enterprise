/** Review and correct one receipt.
 *
 *  What the receipt is comes first - shop, amount, when - then the lines, then the things
 *  you do to a receipt: its category, who paid, which pocket. Editing the header is a tap
 *  away rather than three open text boxes, because looking at a receipt is common and
 *  correcting its shop name is rare.
 *
 *  The photo sits beside the lines on a wide screen so a number can be checked against the
 *  paper without leaving the page; on a phone it folds away once the receipt is confirmed.
 *  Every edit is recorded as a correction server-side, and mapping a line to a product
 *  teaches the app that mapping for every future receipt - which is what turns a pile of
 *  receipts into price history.
 */

import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, type Category, type Item, type Product, type ReceiptDetail } from "../lib/api";
import {
  KIND_LABELS, PAYMENT_LABELS, REVIEW_REASONS, STATUS_LABELS, dateTime, dayTime, fromLocalInput,
  ft, qty, toLocalInput,
} from "../lib/format";
import ReceiptCategory from "../components/ReceiptCategory";
import PocketAndGoal from "../components/PocketAndGoal";
import SplitBill from "../components/SplitBill";
import { AsyncBlock, Card, useAsync } from "../components/ui";

const KINDS = ["item", "deposit", "discount", "rounding", "fee"];

const BADGE: Record<string, string> = {
  needs_review: "badge warn",
  failed: "badge bad",
  confirmed: "badge good",
};

export default function Review() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const state = useAsync(() => api.receipt(id), [id]);
  const categories = useAsync(() => api.categories(), []);
  const products = useAsync(() => api.products(), []);
  const [busy, setBusy] = useState(false);

  // While a re-extraction is in flight the page would otherwise sit on the old parse
  // until manually reloaded, so reprocessing would appear to do nothing.
  const status = state.data?.status;
  const inFlight = status === "pending" || status === "processing";
  const reload = state.reload;
  useEffect(() => {
    if (!inFlight) return;
    const timer = window.setInterval(reload, 2500);
    return () => window.clearInterval(timer);
  }, [inFlight, reload]);

  const act = useCallback(
    async (action: () => Promise<unknown>) => {
      setBusy(true);
      try {
        await action();
        state.reload();
      } finally {
        setBusy(false);
      }
    },
    [state],
  );

  return (
    <AsyncBlock state={state}>
      {(receipt) => {
        const lines = (
          <Lines
            receipt={receipt}
            categories={categories.data ?? []}
            products={products.data ?? []}
            onChanged={() => { state.reload(); products.reload(); }}
          />
        );
        const rest = (
          <>
            <ReceiptCategory
              receipt={receipt}
              categories={categories.data ?? []}
              onSaved={() => state.reload()}
            />
            <SplitBill receipt={receipt} onSaved={() => state.reload()} />
            <PocketAndGoal receipt={receipt} onSaved={() => state.reload()} />
            <Card title="Műveletek">
              <div className="row">
                {/* Reading the photo again only means something when there is a photo. */}
                {receipt.pages > 0 && (
                  <button className="btn" disabled={busy} onClick={() => act(() => api.reprocess(receipt.id))}>
                    ↻ Újrafeldolgozás
                  </button>
                )}
                <button
                  className="btn danger"
                  disabled={busy}
                  onClick={async () => {
                    if (!confirm("Biztosan törlöd ezt a blokkot?")) return;
                    await api.remove(receipt.id);
                    navigate("/blokkok");
                  }}
                >
                  Törlés
                </button>
              </div>
              {receipt.notes && (
                <p className="muted small" style={{ marginBottom: 0, marginTop: 12 }}>
                  A felismerő megjegyzése: {receipt.notes}
                </p>
              )}
            </Card>
          </>
        );

        return (
          <>
            <div className="row" style={{ marginBottom: 14 }}>
              <Link className="btn" to="/blokkok">← Blokkok</Link>
              <span style={{ flex: 1 }} />
              <span className={BADGE[receipt.status] ?? "badge"}>
                {STATUS_LABELS[receipt.status] ?? receipt.status}
              </span>
            </div>

            <Summary
              receipt={receipt}
              busy={busy}
              onSave={(patch) => act(() => api.patchReceipt(receipt.id, patch))}
              onConfirm={() => act(() => api.confirm(receipt.id))}
            />

            {receipt.review_reasons?.length ? (
              <Card title="Ellenőrizd ezeket">
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {receipt.review_reasons.map((reason) => (
                    <li key={reason}>{REVIEW_REASONS[reason] ?? reason}</li>
                  ))}
                </ul>
              </Card>
            ) : null}

            {receipt.error && (
              <Card title="Feldolgozási hiba">
                <p className="error" style={{ margin: 0 }}>{receipt.error}</p>
              </Card>
            )}

            {/* Beside each other on a wide screen, one after the other on a phone. With a
                photo it goes next to the lines, so they can be checked against each other. */}
            <div className="grid cols-2" style={{ marginTop: 14, alignItems: "start" }}>
              {receipt.pages > 0 ? (
                <>
                  <Photo receipt={receipt} />
                  <div>{lines}{rest}</div>
                </>
              ) : (
                <>
                  <div>{lines}</div>
                  <div>{rest}</div>
                </>
              )}
            </div>
          </>
        );
      }}
    </AsyncBlock>
  );
}

/** Shop, amount and when, with the header fields behind a Javítás button. */
function Summary({ receipt, busy, onSave, onConfirm }: {
  receipt: ReceiptDetail;
  busy: boolean;
  onSave: (patch: Record<string, unknown>) => Promise<void>;
  onConfirm: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const inFlight = receipt.status === "pending" || receipt.status === "processing";

  const details = [
    receipt.purchased_at ? dayTime(receipt.purchased_at) : "nincs dátum",
    PAYMENT_LABELS[receipt.payment_method] ?? null,
    receipt.source === "manual" ? "kézzel rögzítve" : null,
    receipt.source === "recurring" ? "↻ rendszeres tételből" : null,
  ].filter(Boolean);

  return (
    <section className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
        <h1 style={{ overflowWrap: "anywhere" }}>
          {receipt.merchant_name ?? receipt.merchant_raw_name ?? (inFlight ? "Felismerés…" : "Ismeretlen bolt")}
        </h1>
        <span style={{ fontSize: "1.35rem", fontWeight: 680, whiteSpace: "nowrap" }} className="mono">
          {ft(receipt.total_gross)}
        </span>
      </div>
      <p className="muted small" style={{ margin: "4px 0 0" }}>{details.join(" · ")}</p>

      {!editing && (
        <div className="row" style={{ marginTop: 12 }}>
          {receipt.status !== "confirmed" && !inFlight && (
            <button className="btn primary" disabled={busy} onClick={onConfirm}>
              ✓ Rendben, megerősítem
            </button>
          )}
          <button className="btn" onClick={() => setEditing(true)} disabled={inFlight}>
            ✎ Javítás
          </button>
        </div>
      )}

      {editing && (
        // Keyed on when the parse itself was last rewritten. The form seeds its state on
        // mount, so a re-extraction must remount it or it would keep showing - and on save
        // write back - values from the previous parse.
        <HeaderForm
          key={`${receipt.id}:${receipt.parsed_at ?? ""}`}
          receipt={receipt}
          busy={busy}
          onCancel={() => setEditing(false)}
          onSave={async (patch) => {
            await onSave(patch);
            setEditing(false);
          }}
        />
      )}
    </section>
  );
}

function HeaderForm({ receipt, onSave, onCancel, busy }: {
  receipt: ReceiptDetail;
  onSave: (patch: Record<string, unknown>) => Promise<void>;
  onCancel: () => void;
  busy: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const [merchant, setMerchant] = useState(receipt.merchant_name ?? receipt.merchant_raw_name ?? "");
  const [total, setTotal] = useState(receipt.total_gross ?? "");
  const [purchasedAt, setPurchasedAt] = useState(toLocalInput(receipt.purchased_at));

  const dirty =
    merchant !== (receipt.merchant_name ?? receipt.merchant_raw_name ?? "") ||
    String(total) !== String(receipt.total_gross ?? "") ||
    purchasedAt !== toLocalInput(receipt.purchased_at);

  return (
    <div style={{ marginTop: 14 }}>
      <div className="field">
        <label htmlFor="merchant">Bolt</label>
        <input id="merchant" value={merchant} onChange={(e) => setMerchant(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="purchased">Vásárlás ideje</label>
        <input id="purchased" type="datetime-local" value={purchasedAt}
               onChange={(e) => setPurchasedAt(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="total">Végösszeg (Ft)</label>
        <input id="total" inputMode="decimal" value={String(total)}
               onChange={(e) => setTotal(e.target.value)} />
      </div>

      <p className="muted" style={{ fontSize: "0.8rem", margin: "0 0 12px" }}>
        Kerekítés: {ft(receipt.rounding)} · Kedvezmény: {ft(receipt.discount_total)}
        {receipt.receipt_no ? ` · Nyugta: ${receipt.receipt_no}` : ""}
        {receipt.parsed_at ? ` · Feldolgozva: ${dateTime(receipt.parsed_at)}` : ""}
      </p>

      {error && <p className="error">{error}</p>}
      <div className="row">
        <button
          className="btn primary"
          disabled={busy || !dirty}
          onClick={async () => {
            setError(null);
            try {
              await onSave({
                merchant_name: merchant || null,
                total_gross: total === "" ? null : total,
                purchased_at: fromLocalInput(purchasedAt),
              });
            } catch (err) {
              // The form stays open with what was typed, so it can be corrected.
              setError((err as Error).message);
            }
          }}
        >
          Mentés
        </button>
        <button className="btn" onClick={onCancel}>Mégse</button>
      </div>
    </div>
  );
}

/** The photograph, folded away once the receipt is confirmed on a phone.
 *
 *  Reviewing a multi-part receipt means checking lines against the section they came from,
 *  so the parts stay separate and numbered rather than being stitched into one image. The
 *  page number is the same one the extraction saw, in the same order.
 */
function Photo({ receipt }: { receipt: ReceiptDetail }) {
  const { id, pages } = receipt;
  const [page, setPage] = useState(0);
  // A different receipt may have fewer pages than the one shown before it.
  const current = Math.min(page, pages - 1);
  // Open while there is checking to do, and always where there is room beside the lines.
  const [open] = useState(
    () => receipt.status !== "confirmed" || window.matchMedia?.("(min-width: 561px)").matches,
  );

  return (
    <details className="card" open={open}>
      <summary style={{ cursor: "pointer", fontWeight: 650, minHeight: 28 }}>
        {pages > 1 ? `📷 A blokk fotója (${pages} rész)` : "📷 A blokk fotója"}
      </summary>
      <div style={{ marginTop: 12 }}>
        {pages > 1 && (
          <div className="row" style={{ gap: 6, marginBottom: 10 }}>
            {Array.from({ length: pages }, (_, index) => (
              <button
                key={index}
                className="btn"
                onClick={() => setPage(index)}
                aria-pressed={index === current}
              >
                {index + 1}. rész
              </button>
            ))}
          </div>
        )}
        <a href={api.imageUrl(id, current)} target="_blank" rel="noreferrer">
          <img
            src={api.imageUrl(id, current)}
            alt={pages > 1 ? `A blokk ${current + 1}. része` : "A blokk fotója"}
            style={{ width: "100%", borderRadius: 8, border: "1px solid var(--border)" }}
          />
        </a>
      </div>
    </details>
  );
}

function Lines({ receipt, categories, products, onChanged }: {
  receipt: ReceiptDetail;
  categories: Category[];
  products: Product[];
  onChanged: () => void;
}) {
  return (
    <Card title="Tételek" note={`${receipt.items.length} sor`}>
      {receipt.items.length === 0 ? (
        <p className="muted" style={{ margin: 0 }}>Nincs felismert tétel.</p>
      ) : (
        <ul className="rows">
          {receipt.items.map((item) => (
            <li key={item.id}>
              <Line
                item={item}
                merchantId={receipt.merchant_id}
                categories={categories}
                products={products}
                onChanged={onChanged}
              />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Line({ item, merchantId, categories, products, onChanged }: {
  item: Item;
  merchantId: string | null;
  categories: Category[];
  products: Product[];
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  async function patch(body: Record<string, unknown>) {
    setSaving(true);
    try {
      await api.patchItem(item.id, body);
      onChanged();
    } finally {
      setSaving(false);
    }
  }

  async function mapToNewProduct() {
    const name = prompt("Termék neve (ez lesz a közös név minden boltban):", item.raw_name);
    if (!name) return;
    setSaving(true);
    try {
      const product = await api.createProduct({ canonical_name: name }, item.raw_name, merchantId ?? undefined);
      await api.patchItem(item.id, { product_id: product.id, remember_mapping: true });
      onChanged();
    } finally {
      setSaving(false);
    }
  }

  const quantity = Number(item.quantity ?? 1);
  const category = categories.find((c) => c.id === item.category_id)?.name;
  const details = [
    quantity !== 1 || (item.unit && item.unit !== "db")
      ? `${qty(item.quantity, item.unit)} × ${ft(item.unit_price)}`
      : null,
    item.kind !== "item" ? KIND_LABELS[item.kind] ?? item.kind : (category ?? "besorolatlan"),
  ].filter(Boolean);

  return (
    <>
      <button className="list-row" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <span className="title" style={{ fontWeight: 550 }}>{item.raw_name}</span>
        <span className="amount">{ft(item.gross_amount)}</span>
        <span className="meta">
          {details.join(" · ")}
          {item.kind === "item" && item.product_id && <span title="Termékhez társítva"> · ✓ termék</span>}
        </span>
        <span className="side muted" aria-hidden>{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "0 12px",
          padding: "4px 0 12px",
        }}>
          <div className="field">
            <label>Típus</label>
            <select defaultValue={item.kind} disabled={saving}
                    onChange={(e) => patch({ kind: e.target.value })}>
              {KINDS.map((kind) => (
                <option key={kind} value={kind}>{KIND_LABELS[kind] ?? kind}</option>
              ))}
            </select>
          </div>

          <div className="field">
            <label>Kategória</label>
            <select defaultValue={item.category_id ?? ""} disabled={saving}
                    onChange={(e) => patch({ category_id: e.target.value || null })}>
              <option value="">– nincs –</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>

          <div className="field">
            <label>Összeg</label>
            <input defaultValue={String(item.gross_amount ?? "")} inputMode="decimal" disabled={saving}
                   onBlur={(e) => {
                     if (e.target.value !== String(item.gross_amount ?? "")) {
                       patch({ gross_amount: e.target.value || null });
                     }
                   }} />
          </div>

          {item.kind === "item" && (
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <label>Termék (ár-követéshez)</label>
              <div className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
                <select defaultValue={item.product_id ?? ""} disabled={saving} style={{ flex: 1, minWidth: 0 }}
                        onChange={(e) =>
                          patch({ product_id: e.target.value || null, remember_mapping: !!e.target.value })
                        }>
                  <option value="">– nincs –</option>
                  {products.map((product) => (
                    <option key={product.id} value={product.id}>{product.canonical_name}</option>
                  ))}
                </select>
                <button className="btn" disabled={saving} onClick={mapToNewProduct} title="Új termék ebből a sorból"
                        style={{ flex: "none" }}>
                  + Új
                </button>
              </div>
              <span className="muted" style={{ fontSize: "0.78rem" }}>
                Megjegyzi, hogy ebben a boltban ez a sor ezt a terméket jelenti.
              </span>
            </div>
          )}
        </div>
      )}
    </>
  );
}
