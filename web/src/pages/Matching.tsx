/** Termékek: turning receipt line text into products, without typing each one.
 *
 *  Every till spells things differently: `PEPSI 1,5L`, `Pepsi Cola 1.5 l`, `PEPSI COLA
 *  1500ML`. Until those are one product they are three price histories and the
 *  cheapest-shop comparison has nothing to compare.
 *
 *  The colour is the whole interface. Green means the names normalise identically and the
 *  app already linked them - nothing to do. Yellow means close enough to be worth a tap.
 *  Red is a starting point and no more. The split exists because a wrong link is silent:
 *  it quietly corrupts a price history and nobody notices for months, so anything short of
 *  certain asks first.
 *
 *  Only yellow and red are listed here. Green needs nothing from you - the worker turns it
 *  into products every hour - so it is one line at the bottom, not forty cards above the
 *  four that matter.
 */

import { useEffect, useState } from "react";

import { api, type Suggestion } from "../lib/api";
import { ft } from "../lib/format";
import { AsyncBlock, Card, useAsync } from "../components/ui";

// A spelling this far from the main one's price - half, or one and a half times - is flagged.
// Not unticked: a different shop, a multipack or an akció can all explain it, and only you
// know which. But lactose-free beside regular, or a premium line beside the house brand,
// usually shows up here first.
const PRICE_GAP = 1.5;

/** How far a price is from the reference, or null when either is missing. */
function priceGap(price: number | null, reference: number | null): number | null {
  if (price == null || reference == null || price <= 0 || reference <= 0) return null;
  return price / reference - 1;
}

const BANDS: Record<string, { label: string; className: string; hint: string }> = {
  green: {
    label: "Biztos",
    className: "good",
    hint: "Betűre egyezik – ezt magától összekapcsolja.",
  },
  yellow: {
    label: "Valószínű",
    className: "warn",
    hint: "Nagyon hasonló, de nem azonos. Vedd ki a pipát abból, ami más termék.",
  },
  red: {
    label: "Bizonytalan",
    className: "bad",
    hint: "Csak tipp. Csak azt hagyd bepipálva, ami tényleg ugyanaz.",
  },
};

export default function Matching() {
  const [reload, setReload] = useState(0);
  // Only the groups that need you: the certain ones become products by themselves.
  const suggestions = useAsync(() => api.suggestions(false), [reload]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<
    { linked: number; created: number; categorised: number } | null
  >(null);

  // What the worker does every hour, now: link lines to the products they letter-for-letter
  // match, and turn the names with a single spelling into products of their own.
  async function autolink() {
    setBusy("__autolink");
    setError(null);
    setDone(null);
    try {
      const result = await api.autolink();
      setDone(result);
      setReload((n) => n + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function confirm(
    group: Suggestion, members: string[], canonicalName: string, productId: string | null,
  ) {
    setBusy(group.suggested_name);
    setError(null);
    try {
      // Only the ticked spellings. The rest stay unmapped and come back as a group of their
      // own - which, for lactose-free beside regular, is exactly the second product.
      await api.applySuggestion({
        raw_names: members,
        canonical_name: canonicalName,
        product_id: productId ?? undefined,
      });
      setReload((n) => n + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <h1 style={{ marginBottom: 4 }}>Termékek</h1>
      <p className="muted small" style={{ marginTop: 0, marginBottom: 14 }}>
        Ugyanaz a termék boltonként máshogy van kiírva. Amit összekapcsolsz, egy ártörténet
        lesz – és összevethető, hol olcsóbb.
      </p>

      <AsyncBlock state={suggestions}>
        {(data) => (
          <>
            <Card
              title="Döntésre vár"
              note={data.groups.length ? `${data.groups.length} csoport` : undefined}
            >
              {error && <p className="error">{error}</p>}
              {data.groups.length === 0 ? (
                <p className="muted" style={{ margin: 0 }}>
                  Nincs eldöntendő: minden hasonló nevet összekapcsoltál.
                </p>
              ) : (
                data.groups.map((group, index) => (
                  <Group
                    key={group.suggested_name}
                    group={group}
                    first={index === 0}
                    // What to do with a band is said once, at its first group - not four
                    // times in a row.
                    hint={data.groups.findIndex((g) => g.band === group.band) === index}
                    busy={busy === group.suggested_name}
                    onConfirm={confirm}
                  />
                ))
              )}
            </Card>

            <Card title="Magától megy">
              <p className="muted small" style={{ marginTop: 0 }}>
                {data.exact_groups > 0
                  ? `${data.exact_groups} név betűre egyezik egy másikkal, vagy csak egyféleképp ` +
                    "fordul elő: ezekből óránként magától lesz termék, nincs vele dolgod."
                  : "Ami egyértelmű, az már mind termék."}
              </p>
              <button className="btn" onClick={autolink} disabled={busy === "__autolink"}>
                {busy === "__autolink" ? "Rendezés…" : "Rendezés most"}
              </button>
              {done !== null && (
                <p className="small" style={{ marginBottom: 0, color: "var(--good-text)" }}>
                  {done.linked || done.created || done.categorised ? (
                    <>
                      {done.created > 0 && `${done.created} új termék. `}
                      {done.linked > 0 && `${done.linked} sor kapott terméket. `}
                      {done.categorised > 0 && `${done.categorised} sor kapott kategóriát.`}
                    </>
                  ) : (
                    "Nem volt mit rendezni."
                  )}
                </p>
              )}
            </Card>
          </>
        )}
      </AsyncBlock>
    </>
  );
}

function Group({ group, first, hint, busy, onConfirm }: {
  group: Suggestion;
  first: boolean;
  hint: boolean;
  busy: boolean;
  onConfirm: (
    group: Suggestion, members: string[], canonicalName: string, productId: string | null,
  ) => void;
}) {
  // Every spelling starts ticked: the grouping is usually right, and unticking the odd one
  // out is one tap where re-ticking five would be five.
  const [picked, setPicked] = useState<Set<string>>(() => new Set(group.members));
  const chosen = group.members.filter((member) => picked.has(member));

  // The existing product only applies while one of the spellings that *are* that product is
  // still ticked. Untick those and the rest would otherwise be filed under it anyway - the
  // regular milk merged into the lactose-free one because the box that named it stayed.
  const joinsProduct =
    group.product_id !== null && chosen.some((member) => group.product_members.includes(member));

  // Pre-filled with the spelling seen most often, because that is the one you recognise -
  // but editable, since the tidiest name is rarely the one the till printed.
  const [name, setName] = useState(group.product_name ?? group.suggested_name);
  useEffect(() => {
    // The product's name stops being right the moment the product stops applying: saving
    // under it would find that product by name and join it all the same.
    if (!joinsProduct && group.product_name && name === group.product_name) {
      setName(chosen[0] ?? group.suggested_name);
    }
  }, [joinsProduct]); // eslint-disable-line react-hooks/exhaustive-deps

  const band = BANDS[group.band] ?? BANDS.red;
  const several = group.members.length > 1;

  // Compared against the most-bought spelling, which is first in the list and names the
  // group - the price you already know. A median would put two members either side of
  // an average neither of them costs.
  const priceOf = (member: string) => {
    const value = group.member_prices[member];
    return value == null ? null : Number(value);
  };
  const reference = priceOf(group.members[0]);

  function toggle(member: string) {
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(member)) next.delete(member);
      else next.add(member);
      return next;
    });
  }

  return (
    <div style={first ? undefined : { borderTop: "1px solid var(--grid)", paddingTop: 12, marginTop: 12 }}>
      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <span className={`badge ${band.className}`}>
          {band.label} · {Math.round(group.score * 100)}%
        </span>
        <span className="muted" style={{ fontSize: "0.82rem" }}>
          {group.occurrences}× · {ft(group.total_spent)}
        </span>
      </div>

      {several ? (
        <div style={{ margin: "0 0 8px" }}>
          {group.members.map((member) => (
            <label
              key={member}
              className="check"
              style={{
                color: picked.has(member) ? undefined : "var(--ink-muted)",
                textDecoration: picked.has(member) ? undefined : "line-through",
              }}
            >
              <input
                type="checkbox"
                checked={picked.has(member)}
                onChange={() => toggle(member)}
                disabled={busy}
              />
              <span style={{ flex: 1, minWidth: 0 }}>{member}</span>
              <PriceTag
                price={priceOf(member)}
                gap={member === group.members[0] ? null : priceGap(priceOf(member), reference)}
              />
              <span className="muted" style={{ fontSize: "0.78rem", minWidth: "2.2em", textAlign: "right" }}>
                {group.member_occurrences[member] ?? 0}×
              </span>
            </label>
          ))}
        </div>
      ) : (
        <div className="muted" style={{ marginBottom: 8, fontSize: "0.86rem" }}>
          {group.members[0]}
        </div>
      )}

      {joinsProduct && (
        <p className="muted" style={{ fontSize: "0.82rem", marginTop: 0 }}>
          Meglévő termékhez kapcsolódik: <strong>{group.product_name}</strong>
        </p>
      )}

      {hint && (
        <p className="muted" style={{ fontSize: "0.8rem", marginTop: 0 }}>
          {band.hint}
        </p>
      )}

      <div className="row" style={{ gap: 8 }}>
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          aria-label="Termék neve"
          style={{ flex: "2 1 180px" }}
        />
        <button
          className="btn primary"
          style={{ flex: "1 1 120px" }}
          disabled={busy || !name.trim() || chosen.length === 0}
          onClick={() =>
            onConfirm(group, chosen, name.trim(), joinsProduct ? group.product_id : null)
          }
        >
          {busy
            ? "Mentés…"
            : several && chosen.length < group.members.length
              ? `Összekapcsolás (${chosen.length})`
              : "Összekapcsolás"}
        </button>
      </div>
      {several && chosen.length < group.members.length && chosen.length > 0 && (
        <p className="muted" style={{ fontSize: "0.78rem", marginBottom: 0 }}>
          A kihagyottak a listán maradnak, és külön csoportként jönnek vissza.
        </p>
      )}
    </div>
  );
}

function PriceTag({ price, gap }: { price: number | null; gap: number | null }) {
  if (price == null) return null;
  const ratio = gap === null ? 1 : 1 + gap;
  const far = ratio >= PRICE_GAP || 1 / ratio >= PRICE_GAP;
  return (
    <span style={{ textAlign: "right", whiteSpace: "nowrap", fontSize: "0.82rem" }}>
      <span className={far ? undefined : "muted"}>{ft(price)}</span>
      {far && gap !== null && (
        <span
          className="badge warn"
          style={{ marginLeft: 6, fontSize: "0.72rem" }}
          title="Ennyivel tér el a legtöbbször vett írásmód árától – lehet, hogy más termék."
        >
          {gap > 0 ? "+" : "−"}{Math.round(Math.abs(gap) * 100)}%
        </span>
      )}
    </span>
  );
}
