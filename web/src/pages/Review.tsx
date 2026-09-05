/** Review and correct one receipt.
 *
 *  The photo sits beside the parsed fields so a number can be checked against the paper
 *  without leaving the page. Every edit is recorded as a correction server-side, and
 *  mapping a line to a product teaches the app that mapping for every future receipt -
 *  which is what turns a pile of receipts into price history.
 */

import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, type Item, type Product, type ReceiptDetail } from "../lib/api";
import {
  KIND_LABELS, REVIEW_REASONS, STATUS_LABELS, dateTime, fromLocalInput, ft, qty, toLocalInput,
} from "../lib/format";
import { AsyncBlock, Card, useAsync } from "../components/ui";

const KINDS = ["item", "deposit", "discount", "rounding", "fee"];

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
      {(receipt) => (
        <>
          <div className="row" style={{ marginBottom: 14 }}>
            <Link className="btn" to="/blokkok">← Blokkok</Link>
            <span className="spacer" style={{ flex: 1 }} />
            <span className={receipt.status === "needs_review" ? "badge warn" : "badge"}>
              {STATUS_LABELS[receipt.status] ?? receipt.status}
            </span>
          </div>

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

          <div className="grid cols-2" style={{ marginTop: 14 }}>
            <Card title={receipt.pages > 1 ? `A blokk (${receipt.pages} rész)` : "A blokk"}>
              <ReceiptPhoto id={receipt.id} pages={receipt.pages} />
            </Card>

            <div>
              {/* Keyed on when the parse itself was last rewritten. The form seeds its
                  state on mount, so a re-extraction must remount it or it would keep
                  showing - and on save write back - values from the previous parse.
                  Deliberately not keyed on confirmed_at: confirming is not a new parse,
                  and remounting there would throw away edits made just before confirming. */}
              <Header
                key={`${receipt.id}:${receipt.parsed_at ?? ""}`}
                receipt={receipt}
                onSave={(patch) => act(() => api.patchReceipt(receipt.id, patch))}
                busy={busy}
              />

              <Card title="Műveletek">
                <div className="row">
                  <button
                    className="btn primary"
                    disabled={busy || receipt.status === "confirmed"}
                    onClick={() => act(() => api.confirm(receipt.id))}
                  >
                    ✓ Megerősítés
                  </button>
                  <button className="btn" disabled={busy} onClick={() => act(() => api.reprocess(receipt.id))}>
                    ↻ Újrafeldolgozás
                  </button>
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
                  <p className="muted" style={{ marginBottom: 0, marginTop: 12 }}>
                    A felismerő megjegyzése: {receipt.notes}
                  </p>
                )}
              </Card>
            </div>
          </div>

          <Card title="Tételek" note={`${receipt.items.length} sor`}>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Megnevezés</th>
                    <th className="num">Menny.</th>
                    <th className="num">Egységár</th>
                    <th className="num">Összeg</th>
                    <th>Típus</th>
                    <th>Termék</th>
                  </tr>
                </thead>
                <tbody>
                  {receipt.items.map((item) => (
                    <ItemRow
                      key={item.id}
                      item={item}
                      merchantId={receipt.merchant_id}
                      categories={categories.data ?? []}
                      products={products.data ?? []}
                      onChanged={() => { state.reload(); products.reload(); }}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </AsyncBlock>
  );
}

/** The photograph, or a switcher across the sections of a receipt captured in parts.
 *
 *  Reviewing a multi-part receipt means checking lines against the section they came from,
 *  so the parts stay separate and numbered rather than being stitched into one image. The
 *  page number is the same one the extraction saw, in the same order.
 */
function ReceiptPhoto({ id, pages }: { id: string; pages: number }) {
  const [page, setPage] = useState(0);
  // A different receipt may have fewer pages than the one shown before it.
  const current = Math.min(page, pages - 1);

  return (
    <>
      {pages > 1 && (
        <div className="row" style={{ gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
          {Array.from({ length: pages }, (_, index) => (
            <button
              key={index}
              className={`btn${index === current ? " primary" : ""}`}
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
    </>
  );
}

function Header({ receipt, onSave, busy }: {
  receipt: ReceiptDetail;
  onSave: (patch: Record<string, unknown>) => void;
  busy: boolean;
}) {
  const [merchant, setMerchant] = useState(receipt.merchant_name ?? receipt.merchant_raw_name ?? "");
  const [total, setTotal] = useState(receipt.total_gross ?? "");
  const [purchasedAt, setPurchasedAt] = useState(toLocalInput(receipt.purchased_at));

  const dirty =
    merchant !== (receipt.merchant_name ?? receipt.merchant_raw_name ?? "") ||
    String(total) !== String(receipt.total_gross ?? "") ||
    purchasedAt !== toLocalInput(receipt.purchased_at);

  return (
    <Card title="Fejléc">
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
        Fizetés: {receipt.payment_method} · Kerekítés: {ft(receipt.rounding)} ·
        Kedvezmény: {ft(receipt.discount_total)}
        {receipt.receipt_no ? ` · Nyugta: ${receipt.receipt_no}` : ""}
        {receipt.parsed_at ? ` · Feldolgozva: ${dateTime(receipt.parsed_at)}` : ""}
      </p>

      <button
        className="btn primary"
        disabled={busy || !dirty}
        onClick={() =>
          onSave({
            merchant_name: merchant || null,
            total_gross: total === "" ? null : total,
            purchased_at: fromLocalInput(purchasedAt),
          })
        }
      >
        Mentés
      </button>
    </Card>
  );
}

function ItemRow({ item, merchantId, categories, products, onChanged }: {
  item: Item;
  merchantId: string | null;
  categories: { id: string; name: string }[];
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

  return (
    <>
      <tr>
        <td>
          <button
            className="btn"
            style={{ border: "none", background: "none", padding: 0, textAlign: "left" }}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? "▾ " : "▸ "}{item.raw_name}
          </button>
        </td>
        <td className="num">{qty(item.quantity, item.unit)}</td>
        <td className="num">{ft(item.unit_price)}</td>
        <td className="num">{ft(item.gross_amount)}</td>
        <td>{KIND_LABELS[item.kind] ?? item.kind}</td>
        <td>
          {item.product_id ? (
            <span className="badge good">✓ társítva</span>
          ) : item.kind === "item" ? (
            <button className="btn" disabled={saving} onClick={mapToNewProduct}>+ termék</button>
          ) : (
            <span className="muted">–</span>
          )}
        </td>
      </tr>

      {open && (
        <tr>
          <td colSpan={6} style={{ background: "var(--plane)" }}>
            <div className="row" style={{ gap: 12, alignItems: "flex-end" }}>
              <div className="field" style={{ marginBottom: 0, minWidth: 120 }}>
                <label>Típus</label>
                <select defaultValue={item.kind} disabled={saving}
                        onChange={(e) => patch({ kind: e.target.value })}>
                  {KINDS.map((kind) => (
                    <option key={kind} value={kind}>{KIND_LABELS[kind] ?? kind}</option>
                  ))}
                </select>
              </div>

              <div className="field" style={{ marginBottom: 0, minWidth: 170 }}>
                <label>Kategória</label>
                <select defaultValue={item.category_id ?? ""} disabled={saving}
                        onChange={(e) => patch({ category_id: e.target.value || null })}>
                  <option value="">– nincs –</option>
                  {categories.map((category) => (
                    <option key={category.id} value={category.id}>{category.name}</option>
                  ))}
                </select>
              </div>

              <div className="field" style={{ marginBottom: 0, minWidth: 200 }}>
                <label>Termék (ár-követéshez)</label>
                <select defaultValue={item.product_id ?? ""} disabled={saving}
                        onChange={(e) =>
                          patch({ product_id: e.target.value || null, remember_mapping: !!e.target.value })
                        }>
                  <option value="">– nincs –</option>
                  {products.map((product) => (
                    <option key={product.id} value={product.id}>{product.canonical_name}</option>
                  ))}
                </select>
              </div>

              <div className="field" style={{ marginBottom: 0, maxWidth: 120 }}>
                <label>Összeg</label>
                <input defaultValue={String(item.gross_amount ?? "")} inputMode="decimal" disabled={saving}
                       onBlur={(e) => {
                         if (e.target.value !== String(item.gross_amount ?? "")) {
                           patch({ gross_amount: e.target.value || null });
                         }
                       }} />
              </div>
            </div>
            <p className="muted" style={{ fontSize: "0.78rem", margin: "10px 0 0" }}>
              A termék kiválasztása megjegyzi, hogy ebben a boltban ez a sor ezt a terméket jelenti.
            </p>
          </td>
        </tr>
      )}
    </>
  );
}
