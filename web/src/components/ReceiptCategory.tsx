/** One category for a whole receipt, on the receipt's own page.
 *
 *  A restaurant bill, a pharmacy visit, a hardware run is one kind of spending however many
 *  lines it prints, and choosing that once is what you want here - not opening each line.
 *  Because you are looking at exactly this bill, it replaces the automatic guesses on it
 *  as well as its blanks. A line you filed yourself is never touched: that was a decision,
 *  not a guess, and the card says how many of those it is leaving alone.
 */

import { useMemo, useState } from "react";

import { api, type Category, type ReceiptDetail } from "../lib/api";
import { groupCategories } from "../lib/categories";
import { Card } from "./ui";

export default function ReceiptCategory({ receipt, categories, onSaved }: {
  receipt: ReceiptDetail;
  categories: Category[];
  onSaved: () => void;
}) {
  const [rememberShop, setRememberShop] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const groups = useMemo(() => groupCategories(categories), [categories]);

  const goods = receipt.items.filter((item) => item.kind === "item");
  if (goods.length === 0) return null;

  const nameOf = (id: string | null) =>
    id === null ? "besorolatlan" : categories.find((c) => c.id === id)?.name ?? "?";
  const counts = new Map<string | null, number>();
  for (const item of goods) counts.set(item.category_id, (counts.get(item.category_id) ?? 0) + 1);
  const mine = goods.filter((item) => item.category_source === "manual").length;
  const shop = receipt.merchant_name ?? "Ez a bolt";

  let now: string;
  if (counts.size === 1) {
    const [only] = counts.keys();
    now = only === null
      ? "Még nincs kategóriája."
      : `${nameOf(only)} – mind a ${goods.length} tétel.`;
  } else {
    now = [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([id, n]) => `${nameOf(id)} ${n}`)
      .join(" · ");
  }

  async function file(category: Category) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const done = await api.fileReceipt(receipt.id, category.id, rememberShop, true);
      setMessage(
        `✓ ${category.name} · ${done.lines} tétel` +
          (done.merchant_id ? ` · ${shop} mostantól mindig ez` : "") +
          (done.spread > 0 ? ` (+${done.spread} tétel a többi blokkján)` : ""),
      );
      setRememberShop(false);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Kategória">
      <p style={{ marginTop: 0, fontSize: "0.9rem" }}>{now}</p>

      {receipt.merchant_id && (
        <label style={{ display: "flex", alignItems: "center", gap: 10, minHeight: 40, fontSize: "0.88rem" }}>
          <input
            type="checkbox"
            checked={rememberShop}
            onChange={(event) => setRememberShop(event.target.checked)}
            disabled={busy}
            style={{ width: 22, height: 22, flex: "0 0 auto" }}
          />
          <span>{shop} mindig ez legyen – a többi blokkja is</span>
        </label>
      )}

      <select
        value=""
        disabled={busy || categories.length === 0}
        aria-label="Az egész blokk kategóriája"
        style={{ width: "100%" }}
        onChange={(event) => {
          const category = categories.find((c) => c.id === event.target.value);
          if (category) file(category);
        }}
      >
        <option value="" disabled>{busy ? "Mentés…" : "Az egész blokk legyen…"}</option>
        {groups.map(({ parent, children }) => (
          <optgroup key={parent.id} label={parent.name}>
            <option value={parent.id}>{parent.name}</option>
            {children.map((child) => (
              <option key={child.id} value={child.id}>{child.name}</option>
            ))}
          </optgroup>
        ))}
      </select>

      <p className="muted" style={{ fontSize: "0.8rem", marginBottom: 0 }}>
        {mine > 0
          ? `A kézzel besorolt ${mine} tétel marad, ahogy van. `
          : ""}
        Egy-egy tételt lent, a tétel sorára koppintva sorolhatsz be másképp.
      </p>
      {message && <p style={{ color: "var(--good-text)", fontSize: "0.88rem", marginBottom: 0 }}>{message}</p>}
      {error && <p className="error">{error}</p>}
    </Card>
  );
}
