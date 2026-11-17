/** On a receipt's page: which pocket paid, and whether this was what a goal saved for.
 *
 *  The pocket works like the category: guessed when every line falls under one pocket line
 *  (all Hobbi, say), shown as a guess, and a choice made here always wins - including
 *  "Főszámla", which says no pocket was involved at all (D29).
 *
 *  Linking is per line, all ticked to begin with: the camera was the goal, the SD card
 *  bought with it was not (D30). A linked line is paid from the goal's pocket - or, for a
 *  wishlist item, from its owner's wishlist savings - and leaves the month's spending.
 */

import { useEffect, useMemo, useState } from "react";

import { api, type BudgetLine, type Pocket, type ReceiptDetail, type User, type Wish } from "../lib/api";
import { pocketLabel } from "../lib/budget";
import { ft } from "../lib/format";
import { Card, useAsync } from "./ui";

export default function PocketAndGoal({ receipt, onSaved }: {
  receipt: ReceiptDetail; onSaved: () => void;
}) {
  const pockets = useAsync(() => api.pockets(), []);
  const lines = useAsync(() => api.budgetLines(), []);
  const wishes = useAsync(() => api.wishlist(), []);
  const users = useAsync(() => api.users(), []);
  if (!pockets.data?.length && !wishes.data?.length) return null;
  return (
    <Card title="Zseb és cél">
      <PocketChoice receipt={receipt} pockets={pockets.data ?? []} users={users.data ?? []} onSaved={onSaved} />
      <GoalLink receipt={receipt} lines={lines.data ?? []} wishes={wishes.data ?? []}
                pockets={pockets.data ?? []} onSaved={onSaved} />
    </Card>
  );
}

function PocketChoice({ receipt, pockets, users, onSaved }: {
  receipt: ReceiptDetail; pockets: Pocket[]; users: User[]; onSaved: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const chosen = receipt.pocket_source === "manual";
  const value = chosen ? receipt.pocket_id ?? "main" : "auto";
  const guess = pockets.find((p) => p.id === receipt.pocket_guess);

  async function choose(next: string) {
    setError(null);
    try {
      await api.setReceiptPocket(receipt.id, next === "auto"
        ? { auto: true }
        : { pocket_id: next === "main" ? null : next });
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (!pockets.length) return null;
  return (
    <label style={{ marginBottom: 12 }}>
      Miből fizettétek
      <select value={value} onChange={(e) => choose(e.target.value)}>
        <option value="auto">
          {guess ? `Javaslat: ${pocketLabel(guess, users)} (a kategóriák alapján)` : "Főszámla (nincs javaslat)"}
        </option>
        <option value="main">Főszámla</option>
        {pockets.filter((p) => p.active || p.id === receipt.pocket_id).map((p) => (
          <option key={p.id} value={p.id}>Zseb: {pocketLabel(p, users)}</option>
        ))}
      </select>
      {error && <span className="error">{error}</span>}
    </label>
  );
}

function GoalLink({ receipt, lines, wishes, pockets, onSaved }: {
  receipt: ReceiptDetail; lines: BudgetLine[]; wishes: Wish[]; pockets: Pocket[]; onSaved: () => void;
}) {
  const goals = lines.filter((l) => l.pocket_id && l.active && l.target_amount !== null);
  const open = wishes.filter((w) => !w.bought_on || receipt.items.some((i) => i.wishlist_item_id === w.id));
  const paid = receipt.items.filter((i) => i.kind === "item" || i.kind === "fee");
  const [target, setTarget] = useState("");
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Every unlinked line is ticked to begin with: usually the whole receipt was the thing.
    setTicked(new Set(paid.filter((i) => !i.earmark_id && !i.wishlist_item_id).map((i) => i.id)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [receipt]);

  const linked = useMemo(() => {
    const names = new Map<string, string>();
    for (const l of lines) names.set(`e:${l.id}`, l.name);
    for (const w of wishes) names.set(`w:${w.id}`, w.name);
    const groups = new Map<string, { label: string; ids: string[]; total: number }>();
    for (const item of receipt.items) {
      const key = item.wishlist_item_id ? `w:${item.wishlist_item_id}` : item.earmark_id ? `e:${item.earmark_id}` : null;
      if (!key) continue;
      const group = groups.get(key) ?? { label: names.get(key) ?? "?", ids: [], total: 0 };
      group.ids.push(item.id);
      group.total += Number(item.gross_amount ?? 0);
      groups.set(key, group);
    }
    return [...groups.values()];
  }, [receipt, lines, wishes]);

  if (!goals.length && !open.length && !linked.length) return null;

  async function link() {
    setError(null);
    if (!target) return setError("Válaszd ki, mire vettétek.");
    if (!ticked.size) return setError("Jelöld be, melyik sor volt az.");
    try {
      await api.linkLines(receipt.id, {
        item_ids: [...ticked],
        earmark_id: target.startsWith("e:") ? target.slice(2) : null,
        wishlist_item_id: target.startsWith("w:") ? target.slice(2) : null,
      });
      setTarget("");
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function unlink(ids: string[]) {
    await api.linkLines(receipt.id, { item_ids: ids });
    onSaved();
  }

  const pocketName = (id: string | null) => pockets.find((p) => p.id === id)?.name;

  return (
    <div>
      {linked.map((group) => (
        <div key={group.label} className="row" style={{ justifyContent: "space-between", marginBottom: 6 }}>
          <span>✓ {group.label} <span className="muted small">· {group.ids.length} sor, {ft(group.total)}</span></span>
          <button className="btn" onClick={() => unlink(group.ids)}>Leválasztás</button>
        </div>
      ))}
      <label>
        Célra vagy a kívánságlistáról vettétek?
        <select value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">– nem –</option>
          {goals.length > 0 && (
            <optgroup label="Célok">
              {goals.map((g) => <option key={g.id} value={`e:${g.id}`}>{g.name} ({pocketName(g.pocket_id)})</option>)}
            </optgroup>
          )}
          {open.length > 0 && (
            <optgroup label="Kívánságlista">
              {open.map((w) => <option key={w.id} value={`w:${w.id}`}>{w.name}</option>)}
            </optgroup>
          )}
        </select>
      </label>
      {target && (
        <>
          <div className="cat-picker" style={{ marginTop: 8 }}>
            {paid.map((item) => (
              <label key={item.id}>
                <input type="checkbox" checked={ticked.has(item.id)}
                       onChange={() => {
                         const next = new Set(ticked);
                         if (next.has(item.id)) next.delete(item.id); else next.add(item.id);
                         setTicked(next);
                       }} />
                <span style={{ flex: 1 }}>{item.raw_name}</span>
                <span className="mono">{ft(item.gross_amount)}</span>
              </label>
            ))}
          </div>
          <button className="btn primary" style={{ marginTop: 8 }} onClick={link}>Összekapcsolás</button>
        </>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
