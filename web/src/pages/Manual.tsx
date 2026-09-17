/** Typing in a receipt you no longer have.
 *
 *  The form is deliberately forgiving about the parts you have forgotten: the total defaults
 *  to the sum of the lines, and one line with the shop's name on it is a perfectly valid
 *  entry when all you remember is "Lidl, 4 200 Ft". Everything beyond that is optional detail
 *  you can add if you have it.
 */

import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../lib/api";
import { ft } from "../lib/format";
import { Card } from "../components/ui";

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
      <div className="row page-actions" style={{ marginBottom: 14 }}>
        <h1 style={{ flex: 1 }}>Kézi rögzítés</h1>
        <Link className="btn" to="/">← Fotózás</Link>
      </div>

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
          A Spotify és a többi előfizetés nem ide való – azt elég egyszer beállítani, utána
          magától rögzül minden hónapban.{" "}
          <Link to="/elofizetesek">Előfizetések →</Link>
        </p>
      </Card>
    </>
  );
}
