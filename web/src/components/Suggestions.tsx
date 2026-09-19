/** Turning receipt line text into products, without typing each one.
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
 */

import { useState } from "react";

import { api, type Suggestion } from "../lib/api";
import { ft } from "../lib/format";
import { AsyncBlock, Card, useAsync } from "../components/ui";

const BANDS: Record<string, { label: string; className: string; hint: string }> = {
  green: {
    label: "Biztos",
    className: "good",
    hint: "Betűre egyezik – ezt magától összekapcsolja.",
  },
  yellow: {
    label: "Valószínű",
    className: "warn",
    hint: "Nagyon hasonló, de nem azonos. Nézd meg, és hagyd jóvá.",
  },
  red: {
    label: "Bizonytalan",
    className: "bad",
    hint: "Csak tipp. Akkor kapcsold össze, ha tényleg ugyanaz.",
  },
};

export default function Suggestions() {
  const [reload, setReload] = useState(0);
  const suggestions = useAsync(() => api.suggestions(), [reload]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<
    { linked: number; created: number; categorised: number } | null
  >(null);

  // What is already in the database, brought up to date with what you have mapped since.
  // Only letter-for-letter matches, so there is nothing to check afterwards.
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

  async function confirm(group: Suggestion, canonicalName: string) {
    setBusy(group.suggested_name);
    setError(null);
    try {
      await api.applySuggestion({
        raw_names: group.members,
        canonical_name: canonicalName,
        product_id: group.product_id ?? undefined,
      });
      setReload((n) => n + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <AsyncBlock state={suggestions} empty="Minden tétel be van sorolva.">
      {(data) => (
        <Card
          title="Termékek felismerése"
          note={`${data.unmapped_lines} besorolatlan sor`}
          action={
            <>
              <button
                className="btn"
                onClick={autolink}
                disabled={busy === "__autolink"}
                title="A már eltárolt sorokat összekapcsolja a betűre egyező termékekkel"
              >
                {busy === "__autolink" ? "Keresés…" : "Régiek összekapcsolása"}
              </button>{" "}
              <button className="btn" onClick={() => setReload((n) => n + 1)}>Frissítés</button>
            </>
          }
        >
          <p className="muted" style={{ marginTop: 0 }}>
            Ugyanaz a termék máshogy van kiírva minden boltban. Ha összekapcsolod őket, egy
            ártörténetté válnak – és összehasonlíthatóvá, melyik boltban olcsóbb.
            Az <strong>egyértelmű</strong> eseteket magától elintézi; ide csak az kerül,
            amihez tényleg te kellesz.
          </p>

          {done !== null && (
            <p
              className="muted"
              style={{
                fontSize: "0.86rem",
                color:
                  done.linked || done.created || done.categorised
                    ? "var(--good-text)"
                    : undefined,
              }}
            >
              {done.linked || done.created || done.categorised ? (
                <>
                  {done.created > 0 && `${done.created} új termék. `}
                  {done.linked > 0 && `${done.linked} sor kapott terméket. `}
                  {done.categorised > 0 && `${done.categorised} sor kapott kategóriát.`}
                </>
              ) : (
                "Nem maradt egyértelmű eset – ami lent van, ahhoz te kellesz."
              )}
            </p>
          )}
          {error && <p className="error">{error}</p>}
          {data.groups.length === 0 && (
            <p className="muted" style={{ marginBottom: 0 }}>Nincs több javaslat.</p>
          )}

          {data.groups.map((group) => (
            <Group
              key={group.suggested_name}
              group={group}
              busy={busy === group.suggested_name}
              onConfirm={confirm}
            />
          ))}
        </Card>
      )}
    </AsyncBlock>
  );
}

function Group({ group, busy, onConfirm }: {
  group: Suggestion;
  busy: boolean;
  onConfirm: (group: Suggestion, canonicalName: string) => void;
}) {
  // Pre-filled with the spelling seen most often, because that is the one you recognise -
  // but editable, since the tidiest name is rarely the one the till printed.
  const [name, setName] = useState(group.product_name ?? group.suggested_name);
  const band = BANDS[group.band] ?? BANDS.red;

  return (
    <div
      style={{
        borderTop: "1px solid var(--grid)",
        paddingTop: 12,
        marginTop: 12,
      }}
    >
      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <span className={`badge ${band.className}`}>
          {band.label} · {Math.round(group.score * 100)}%
        </span>
        <span className="muted" style={{ fontSize: "0.82rem" }}>
          {group.occurrences}× · {ft(group.total_spent)}
        </span>
      </div>

      {group.members.length > 1 ? (
        <ul className="muted" style={{ margin: "0 0 8px", paddingLeft: 20, fontSize: "0.86rem" }}>
          {group.members.map((member) => <li key={member}>{member}</li>)}
        </ul>
      ) : (
        <div className="muted" style={{ marginBottom: 8, fontSize: "0.86rem" }}>
          {group.members[0]}
        </div>
      )}

      {group.product_name && (
        <p className="muted" style={{ fontSize: "0.82rem", marginTop: 0 }}>
          Meglévő termékhez kapcsolódik: <strong>{group.product_name}</strong>
        </p>
      )}

      <p className="muted" style={{ fontSize: "0.8rem", marginTop: 0 }}>{band.hint}</p>

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
          disabled={busy || !name.trim()}
          onClick={() => onConfirm(group, name.trim())}
        >
          {busy ? "Mentés…" : "Összekapcsolás"}
        </button>
      </div>
    </div>
  );
}
