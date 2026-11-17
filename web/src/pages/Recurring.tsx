/** Rendszeres: what comes and goes every month - bills, subscriptions and salaries.
 *
 *  Set once, then the plan counts on it every month. A fixed bill (Spotify, the rent) books
 *  itself on its day and shows up in the statistics like a shop does. A variable one (the
 *  electricity) and every salary wait in "Ebben az időszakban" until you say what it came to
 *  or that it arrived. Deactivating stops the future and keeps everything already recorded -
 *  a cancelled subscription is still part of last year.
 */

import { useMemo, useState } from "react";

import { api, type Category, type Person, type Recurring as Rule } from "../lib/api";
import { amountOf, owners, ownerName, plain, todayIso } from "../lib/budget";
import { groupCategories } from "../lib/categories";
import { ft, date as fmtDate } from "../lib/format";
import { useSession } from "../lib/session";
import Occurrences from "../components/Occurrences";
import { AsyncBlock, Card, Empty, useAsync } from "../components/ui";

type Split = "none" | "equal" | "custom";

type Draft = {
  direction: "expense" | "income";
  name: string; merchant_name: string; amount: string;
  amount_mode: "fixed" | "variable";
  cadence: string; day_of_month: string; month_of_year: string; starts_on: string;
  payment_method: string; owner_id: string; payer_id: string; category_id: string;
  pocket_id: string;
  split: Split; percents: Record<string, string>;
};

const MONTHS = ["január", "február", "március", "április", "május", "június", "július",
  "augusztus", "szeptember", "október", "november", "december"];

function blank(direction: "expense" | "income", me: string | null): Draft {
  return {
    direction, name: "", merchant_name: "", amount: "", amount_mode: "fixed",
    cadence: "monthly", day_of_month: String(new Date().getDate()),
    month_of_year: String(new Date().getMonth() + 1), starts_on: todayIso(),
    payment_method: "card",
    // A salary is someone's; a bill is usually the household's.
    owner_id: direction === "income" ? me ?? "" : "",
    payer_id: "", category_id: "", pocket_id: "", split: "none", percents: {},
  };
}

function fromRule(rule: Rule): Draft {
  const shares = rule.default_shares ?? [];
  const percents = Object.fromEntries(shares.map((s) => [s.user_id, plain(s.percent)]));
  const equal = shares.length > 1 && shares.every((s) => Number(s.percent) === Number(shares[0].percent));
  return {
    direction: rule.direction, name: rule.name, merchant_name: rule.merchant_name,
    amount: plain(rule.amount), amount_mode: rule.amount_mode, cadence: rule.cadence,
    day_of_month: String(rule.day_of_month),
    month_of_year: String(rule.month_of_year ?? new Date(rule.starts_on).getMonth() + 1),
    starts_on: rule.starts_on, payment_method: rule.payment_method,
    owner_id: rule.owner_id ?? "", payer_id: rule.payer_id ?? "",
    category_id: rule.category_id ?? "", pocket_id: rule.pocket_id ?? "",
    split: shares.length === 0 ? "none" : equal ? "equal" : "custom", percents,
  };
}

export default function RecurringPage() {
  const [reload, setReload] = useState(0);
  const rules = useAsync(() => api.recurring(), [reload]);
  const occurrences = useAsync(() => api.occurrences(), [reload]);
  const users = useAsync(() => api.users(), []);
  const categories = useAsync(() => api.categories(), []);
  const session = useSession();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const refresh = () => setReload((n) => n + 1);

  const people: Person[] = users.data ?? [];
  const close = () => { setDraft(null); setEditing(null); };

  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Rendszeres</h1>

      <Card title="Ebben az időszakban" note="ami esedékes, és ami már megtörtént">
        <AsyncBlock state={occurrences} empty="Ebben az időszakban nincs esedékes tétel.">
          {(data) => <Occurrences items={data} users={people} onChange={refresh} />}
        </AsyncBlock>
      </Card>

      {draft ? (
        <RuleForm
          draft={draft} setDraft={setDraft} editing={editing} people={people}
          categories={categories.data ?? []}
          onCancel={close}
          onSaved={() => { close(); refresh(); }}
        />
      ) : (
        <Card>
          <p className="muted" style={{ marginTop: 0 }}>
            Ami minden hónapban jön vagy megy: fizetés, albérlet, rezsi, Spotify. Egyszer
            beállítod, utána a terv minden hónapban számol vele.
          </p>
          <div className="row">
            <button className="btn primary" onClick={() => { setDraft(blank("expense", session?.user_id ?? null)); setEditing(null); }}>
              + Kiadás
            </button>
            <button className="btn" onClick={() => { setDraft(blank("income", session?.user_id ?? null)); setEditing(null); }}>
              + Bevétel
            </button>
          </div>
        </Card>
      )}

      <AsyncBlock state={rules}>
        {(data) => (
          <>
            <RuleList
              title="Bevételek" rules={data.filter((r) => r.direction === "income")}
              people={people} onChange={refresh}
              onEdit={(rule) => { setEditing(rule.id); setDraft(fromRule(rule)); window.scrollTo(0, 0); }}
              empty="Még nincs bevétel beállítva – a fizetéseteket érdemes ide felvenni."
            />
            <RuleList
              title="Kiadások" rules={data.filter((r) => r.direction === "expense")}
              people={people} onChange={refresh}
              onEdit={(rule) => { setEditing(rule.id); setDraft(fromRule(rule)); window.scrollTo(0, 0); }}
              empty="Még nincs rendszeres kiadás."
            />
          </>
        )}
      </AsyncBlock>
    </>
  );
}

function RuleList({ title, rules, people, onChange, onEdit, empty }: {
  title: string; rules: Rule[]; people: Person[];
  onChange: () => void; onEdit: (rule: Rule) => void; empty: string;
}) {
  async function toggle(rule: Rule) {
    await api.updateRecurring(rule.id, { ...rule, active: !rule.active });
    onChange();
  }

  async function remove(rule: Rule) {
    if (!window.confirm(`Töröljem a(z) "${rule.name}" tételt? A már rögzítettek megmaradnak.`)) return;
    await api.deleteRecurring(rule.id);
    onChange();
  }

  return (
    <Card title={title}>
      {rules.length === 0 ? <Empty>{empty}</Empty> : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Név</th>
                <th className="num">Összeg</th>
                <th>Mikor</th>
                <th>Következő</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr key={rule.id} style={{ opacity: rule.active ? 1 : 0.55 }}>
                  <td>
                    {rule.name}
                    <span className="tag">{rule.amount_mode === "variable" ? "Változó" : "Fix"}</span>
                    {!rule.active && <span className="muted"> · szünetel</span>}
                    <div className="muted small">
                      {ownerName(people, rule.owner_id)}
                      {rule.payer_id && rule.direction === "expense" && ` · fizeti: ${ownerName(people, rule.payer_id)}`}
                      {rule.default_shares?.length ? " · megosztva" : ""}
                    </div>
                  </td>
                  <td className="num">
                    {rule.amount_mode === "variable" && <span className="muted">~</span>}
                    {ft(rule.amount)}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {rule.cadence === "yearly"
                      ? `évente, ${MONTHS[(rule.month_of_year ?? 1) - 1]} ${rule.day_of_month}.`
                      : `havonta ${rule.day_of_month}.`}
                  </td>
                  <td>{rule.next_charge ? fmtDate(rule.next_charge) : "–"}</td>
                  <td className="num" style={{ whiteSpace: "nowrap" }}>
                    <button className="btn" aria-label="Szerkesztés" onClick={() => onEdit(rule)}>✎</button>{" "}
                    <button className="btn" aria-label={rule.active ? "Szüneteltetés" : "Folytatás"}
                            onClick={() => toggle(rule)}>
                      {rule.active ? "⏸" : "▶"}
                    </button>{" "}
                    <button className="btn" aria-label="Törlés" onClick={() => remove(rule)}>🗑</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function RuleForm({ draft, setDraft, editing, people, categories, onCancel, onSaved }: {
  draft: Draft; setDraft: (draft: Draft) => void; editing: string | null;
  people: Person[]; categories: Category[];
  onCancel: () => void; onSaved: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const groups = useMemo(() => groupCategories(categories), [categories]);
  const pockets = (useAsync(() => api.pockets(), []).data ?? []).filter((p) => p.active || p.id === draft.pocket_id);
  const income = draft.direction === "income";
  const active = people.filter((p) => p.active);
  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch });

  function shares(): { user_id: string; percent: number }[] | null {
    if (income || draft.split === "none") return null;
    if (draft.split === "equal") {
      const each = Math.floor((100 / active.length) * 100) / 100;
      return active.map((p, i) => ({
        user_id: p.id,
        // The last person takes the rounding, so three people still add up to 100.
        percent: i === active.length - 1 ? Math.round((100 - each * (active.length - 1)) * 100) / 100 : each,
      }));
    }
    return active
      .map((p) => ({ user_id: p.id, percent: amountOf(draft.percents[p.id] ?? "") ?? 0 }))
      .filter((s) => s.percent > 0);
  }

  async function save() {
    setError(null);
    const amount = amountOf(draft.amount);
    if (!draft.name.trim()) return setError("Adj nevet a tételnek.");
    if (amount === null || amount <= 0) return setError("Az összegnek nullánál nagyobbnak kell lennie.");
    const split = shares();
    if (split && !draft.payer_id) return setError("Megosztáshoz add meg, ki fizeti.");

    const body = {
      direction: draft.direction,
      name: draft.name.trim(),
      merchant_name: income ? "" : draft.merchant_name.trim(),
      amount,
      amount_mode: draft.amount_mode,
      cadence: draft.cadence,
      day_of_month: Number(draft.day_of_month) || 1,
      month_of_year: draft.cadence === "yearly" ? Number(draft.month_of_year) : null,
      payment_method: draft.payment_method,
      starts_on: draft.starts_on,
      active: true,
      owner_id: draft.owner_id || null,
      payer_id: income ? null : draft.payer_id || null,
      category_id: income ? null : draft.category_id || null,
      pocket_id: income ? null : draft.pocket_id || null,
      default_shares: split,
    };

    setBusy(true);
    try {
      if (editing) await api.updateRecurring(editing, body);
      else await api.createRecurring(body);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title={editing ? "Szerkesztés" : income ? "Új rendszeres bevétel" : "Új rendszeres kiadás"}
      action={<button className="btn" onClick={onCancel}>Mégse</button>}
    >
      <div className="grid cols-2" style={{ gap: 10 }}>
        <label>
          Név
          <input value={draft.name} onChange={(e) => set({ name: e.target.value })}
                 placeholder={income ? "pl. Fizetés" : "pl. Albérlet, Villany, Spotify"} autoFocus />
        </label>
        <label>
          {income ? "Kié" : "Kié a tervben"}
          <select value={draft.owner_id} onChange={(e) => set({ owner_id: e.target.value })}>
            {owners(people).map((o) => <option key={o.id ?? "kozos"} value={o.id ?? ""}>{o.name}</option>)}
          </select>
        </label>
        <label>
          {draft.amount_mode === "variable" ? "Várható összeg (Ft)" : "Összeg (Ft)"}
          <input inputMode="decimal" value={draft.amount}
                 onChange={(e) => set({ amount: e.target.value })} placeholder="15 000" />
        </label>
        <label>
          Összeg
          <select value={draft.amount_mode}
                  onChange={(e) => set({ amount_mode: e.target.value as Draft["amount_mode"] })}>
            <option value="fixed">Minden hónapban ugyanannyi</option>
            <option value="variable">Változó (pl. villany)</option>
          </select>
        </label>
        <label>
          Gyakoriság
          <select value={draft.cadence} onChange={(e) => set({ cadence: e.target.value })}>
            <option value="monthly">Havonta</option>
            <option value="yearly">Évente</option>
          </select>
        </label>
        {draft.cadence === "yearly" && (
          <label>
            Melyik hónapban
            <select value={draft.month_of_year} onChange={(e) => set({ month_of_year: e.target.value })}>
              {MONTHS.map((name, i) => <option key={name} value={String(i + 1)}>{name}</option>)}
            </select>
          </label>
        )}
        <label>
          Hányadikán
          <input type="number" min={1} max={31} value={draft.day_of_month}
                 onChange={(e) => set({ day_of_month: e.target.value })} />
        </label>
        <label>
          Mikortól
          <input type="date" value={draft.starts_on} onChange={(e) => set({ starts_on: e.target.value })} />
        </label>

        {!income && (
          <>
            <label>
              Kategória
              <select value={draft.category_id} onChange={(e) => set({ category_id: e.target.value })}>
                <option value="">– nincs –</option>
                {groups.map(({ parent, children }) => (
                  <optgroup key={parent.id} label={parent.name}>
                    <option value={parent.id}>{parent.name}</option>
                    {children.map((child) => <option key={child.id} value={child.id}>{child.name}</option>)}
                  </optgroup>
                ))}
              </select>
            </label>
            <label>
              Szolgáltató
              <input value={draft.merchant_name} onChange={(e) => set({ merchant_name: e.target.value })}
                     placeholder="alapból a név" />
            </label>
            <label>
              Zsebből
              <select value={draft.pocket_id} onChange={(e) => set({ pocket_id: e.target.value })}>
                <option value="">– főszámláról –</option>
                {pockets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
            <label>
              Ki fizeti
              <select value={draft.payer_id} onChange={(e) => set({ payer_id: e.target.value })}>
                <option value="">– nincs megadva –</option>
                {active.map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}
              </select>
            </label>
            {active.length > 1 && (
              <label>
                Megosztás
                <select value={draft.split} onChange={(e) => set({ split: e.target.value as Split })}>
                  <option value="none">Nincs megosztva</option>
                  <option value="equal">Egyenlően</option>
                  <option value="custom">Egyéni arány</option>
                </select>
              </label>
            )}
          </>
        )}
      </div>

      {!income && draft.split === "custom" && (
        <div className="row" style={{ marginTop: 10 }}>
          {active.map((p) => (
            <label key={p.id} style={{ flex: "1 1 120px" }}>
              {p.display_name} (%)
              <input inputMode="decimal" value={draft.percents[p.id] ?? ""}
                     onChange={(e) => set({ percents: { ...draft.percents, [p.id]: e.target.value } })} />
            </label>
          ))}
        </div>
      )}

      <p className="muted small">
        {income
          ? "A bevétel sosem rögzül magától: minden hónapban várja, és te jelölöd, hogy megérkezett."
          : draft.pocket_id
            ? "Zsebből fizetve: a zsebet csökkenti, és nem tervez külön sort – a pénzét a zseb havi befizetése adja."
            : draft.amount_mode === "variable"
            ? "Változó összegnél minden hónapban beírod, mennyi lett; a terv a legutóbbival számol."
            : "Fix összegnél az esedékes napon magától rögzül, megosztva, ha beállítottad. Rövidebb hónapban az utolsó napon."}
      </p>

      {error && <p className="error">{error}</p>}
      <button className="btn primary" onClick={save} disabled={busy}>
        {busy ? "Mentés…" : "Mentés"}
      </button>
    </Card>
  );
}
