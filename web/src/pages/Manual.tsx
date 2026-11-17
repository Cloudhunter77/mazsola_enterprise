/** Typing in a receipt you no longer have - or money that came in.
 *
 *  The form is deliberately forgiving about the parts you have forgotten: the total defaults
 *  to the sum of the lines, and one line with the shop's name on it is a perfectly valid
 *  entry when all you remember is "Lidl, 4 200 Ft". Everything beyond that is optional detail
 *  you can add if you have it.
 *
 *  Income lives here too, behind the Bevétel switch, because a bonus or a refund is the same
 *  kind of thing: one amount you want written down now. A salary is better set up once under
 *  Rendszeres, where it is expected every month and confirmed when it arrives.
 */

import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../lib/api";
import { amountOf as parseAmount, owners, todayIso } from "../lib/budget";
import { ft } from "../lib/format";
import { useSession } from "../lib/session";
import { Card, useAsync } from "../components/ui";

type Line = { name: string; amount: string; quantity: string; kind: string };

const BLANK: Line = { name: "", amount: "", quantity: "1", kind: "item" };

const KINDS = [
  { value: "item", label: "Termék" },
  { value: "deposit", label: "Betétdíj" },
  { value: "discount", label: "Kedvezmény" },
  { value: "fee", label: "Díj" },
];

/** Today in the browser's timezone, formatted for `<input type="datetime-local">`. */
function nowLocal(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 16);
}

/** Accepts `1 234`, `1234`, `1234,56` - whatever gets typed on a Hungarian keyboard. */
function amountOf(raw: string): number | null {
  const cleaned = raw.replace(/\s| /g, "").replace(",", ".");
  if (!cleaned) return null;
  const value = Number(cleaned);
  return Number.isFinite(value) ? value : null;
}

export default function Manual() {
  const [params, setParams] = useSearchParams();
  const income = params.has("bevetel");

  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Kézi rögzítés</h1>
      <div className="segmented" role="group" aria-label="Mit rögzítesz?">
        <button
          className="btn" aria-pressed={!income}
          onClick={() => setParams({}, { replace: true })}
        >
          Kiadás
        </button>
        <button
          className="btn" aria-pressed={income}
          onClick={() => setParams({ bevetel: "" }, { replace: true })}
        >
          Bevétel
        </button>
      </div>
      {income ? <IncomeForm /> : <ExpenseForm />}
    </>
  );
}

function IncomeForm() {
  const navigate = useNavigate();
  const session = useSession();
  const users = useAsync(() => api.users(), []);
  const [owner, setOwner] = useState<string>(session?.user_id ?? "");
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [day, setDay] = useState(todayIso());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setError(null);
    const value = parseAmount(amount);
    if (!name.trim()) return setError("Mi volt ez? Pl. bónusz, visszatérítés.");
    if (value === null || value <= 0) return setError("Adj meg egy nullánál nagyobb összeget.");
    setBusy(true);
    try {
      await api.addIncome({
        user_id: owner || null, name: name.trim(), amount: value, received_on: day,
      });
      navigate("/penz");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <>
      <Card>
        <p className="muted" style={{ marginTop: 0 }}>
          Bónusz, visszatérítés, ajándékba kapott pénz – ami egyszer jön. A fizetést elég egyszer
          beállítani a <Link to="/rendszeres">Rendszeres</Link> alatt; ott minden hónapban
          várja, és egy gombnyomással jelölöd, hogy megérkezett.
        </p>
        <div className="grid cols-2" style={{ gap: 10 }}>
          <label>
            Kié
            <select value={owner} onChange={(event) => setOwner(event.target.value)}>
              {owners(users.data ?? []).map((o) => (
                <option key={o.id ?? "kozos"} value={o.id ?? ""}>{o.name}</option>
              ))}
            </select>
          </label>
          <label>
            Mi volt ez
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="pl. Bónusz"
              autoFocus
            />
          </label>
          <label>
            Összeg (Ft)
            <input
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              placeholder="50 000"
            />
          </label>
          <label>
            Mikor érkezett
            <input type="date" value={day} max={todayIso()}
                   onChange={(event) => setDay(event.target.value)} />
          </label>
        </div>
        {error && <p className="error">{error}</p>}
        <button
          className="btn primary big"
          style={{ width: "100%", marginTop: 12 }}
          onClick={save}
          disabled={busy}
        >
          {busy ? "Mentés…" : "Bevétel mentése"}
        </button>
      </Card>
    </>
  );
}

function ExpenseForm() {
  const navigate = useNavigate();
  const [merchant, setMerchant] = useState("");
  const [when, setWhen] = useState(nowLocal());
  const [payment, setPayment] = useState("card");
  const [lines, setLines] = useState<Line[]>([{ ...BLANK }]);
  const [overrideTotal, setOverrideTotal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const computed = useMemo(
    () =>
      lines.reduce((sum, line) => {
        const value = amountOf(line.amount) ?? 0;
        return sum + (line.kind === "discount" ? -Math.abs(value) : value);
      }, 0),
    [lines],
  );

  function setLine(index: number, patch: Partial<Line>) {
    setLines((current) => current.map((line, i) => (i === index ? { ...line, ...patch } : line)));
  }

  async function save() {
    setError(null);
    if (!merchant.trim()) return setError("Add meg a bolt nevét.");

    const items = lines
      .filter((line) => line.name.trim() && amountOf(line.amount) !== null)
      .map((line) => ({
        raw_name: line.name.trim(),
        gross_amount: amountOf(line.amount) as number,
        quantity: amountOf(line.quantity) ?? 1,
        kind: line.kind,
      }));
    if (!items.length) return setError("Legalább egy sorhoz kell név és összeg.");

    const total = amountOf(overrideTotal);
    setBusy(true);
    try {
      const receipt = await api.createManual({
        merchant_name: merchant.trim(),
        // datetime-local has no zone; the browser's own offset is the right one to assume.
        purchased_at: new Date(when).toISOString(),
        items,
        total_gross: total ?? undefined,
        payment_method: payment,
      });
      navigate(`/blokkok/${receipt.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <>
      <Card>
        <p className="muted" style={{ marginTop: 0 }}>
          Elveszett a blokk, de tudod mit vettél? Írd be. Ugyanúgy beleszámít a
          statisztikákba, mint egy lefotózott blokk – csak nincs hozzá kép.
        </p>

        <div className="grid cols-2" style={{ gap: 10 }}>
          <label>
            Bolt
            <input
              value={merchant}
              onChange={(event) => setMerchant(event.target.value)}
              placeholder="pl. Lidl"
              autoFocus
            />
          </label>
          <label>
            Mikor
            <input
              type="datetime-local"
              value={when}
              onChange={(event) => setWhen(event.target.value)}
            />
          </label>
          <label>
            Fizetés
            <select value={payment} onChange={(event) => setPayment(event.target.value)}>
              <option value="card">Bankkártya</option>
              <option value="cash">Készpénz</option>
              <option value="other">Egyéb</option>
            </select>
          </label>
        </div>
      </Card>

      <Card title="Tételek" action={
        <button className="btn" onClick={() => setLines((c) => [...c, { ...BLANK }])}>
          + Sor
        </button>
      }>
        {lines.map((line, index) => (
          <div
            key={index}
            className="row"
            style={{ gap: 8, marginBottom: 8, alignItems: "flex-end", flexWrap: "wrap" }}
          >
            <label style={{ flex: "3 1 160px" }}>
              {index === 0 && "Megnevezés"}
              <input
                value={line.name}
                onChange={(event) => setLine(index, { name: event.target.value })}
                placeholder="pl. Tej 2,8% 1L"
              />
            </label>
            <label style={{ flex: "0 1 70px" }}>
              {index === 0 && "Menny."}
              <input
                inputMode="decimal"
                value={line.quantity}
                onChange={(event) => setLine(index, { quantity: event.target.value })}
              />
            </label>
            <label style={{ flex: "1 1 100px" }}>
              {index === 0 && "Összeg"}
              <input
                inputMode="decimal"
                value={line.amount}
                onChange={(event) => setLine(index, { amount: event.target.value })}
                placeholder="Ft"
              />
            </label>
            <label style={{ flex: "1 1 110px" }}>
              {index === 0 && "Típus"}
              <select
                value={line.kind}
                onChange={(event) => setLine(index, { kind: event.target.value })}
              >
                {KINDS.map((kind) => (
                  <option key={kind.value} value={kind.value}>{kind.label}</option>
                ))}
              </select>
            </label>
            {lines.length > 1 && (
              <button
                className="btn"
                aria-label={`${index + 1}. sor törlése`}
                onClick={() => setLines((c) => c.filter((_, i) => i !== index))}
              >
                ×
              </button>
            )}
          </div>
        ))}

        <div className="row" style={{ marginTop: 14, alignItems: "flex-end", gap: 12 }}>
          <div style={{ flex: 1 }}>
            <div className="muted" style={{ fontSize: "0.84rem" }}>Sorok összege</div>
            <div style={{ fontSize: "1.3rem", fontWeight: 680 }}>{ft(computed)}</div>
          </div>
          <label style={{ flex: "0 1 170px" }}>
            Végösszeg felülírása
            <input
              inputMode="decimal"
              value={overrideTotal}
              onChange={(event) => setOverrideTotal(event.target.value)}
              placeholder="ha eltér"
            />
          </label>
        </div>

        {error && <p className="error">{error}</p>}

        <button
          className="btn primary big"
          style={{ width: "100%", marginTop: 12 }}
          onClick={save}
          disabled={busy}
        >
          {busy ? "Mentés…" : "Mentés"}
        </button>
      </Card>

      <Card title="Ismétlődő kiadás?">
        <p className="muted" style={{ margin: 0 }}>
          A Spotify, a rezsi és a többi rendszeres tétel nem ide való – azt elég egyszer
          beállítani, utána minden hónapban számol vele a terv.{" "}
          <Link to="/rendszeres">Rendszeres →</Link>
        </p>
      </Card>
    </>
  );
}
