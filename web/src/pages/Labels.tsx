/** Photographing shelf labels, so a price can be recorded without buying the thing.
 *
 *  Built for standing in an aisle with one hand free. The shop is asked once and then
 *  stays put for the whole visit, because a shelf label almost never says where it is and
 *  answering that question twenty times would make the feature not worth using. The camera
 *  button is the biggest thing on the screen, and each photo goes up on its own so a weak
 *  signal costs you one label rather than the lot.
 *
 *  What comes back is not spending. A price seen on a shelf never reaches the monthly
 *  total - it only feeds price history, where it is drawn differently from a purchase.
 */

import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, type LabelPhoto } from "../lib/api";
import { AsyncBlock, Card, useAsync } from "../components/ui";

const SHOP_KEY = "receipt-tracker-shop";

/** The shops you are most likely to be standing in, for one-tap selection. */
const COMMON_SHOPS = ["Aldi", "Lidl", "Tesco", "Spar", "Penny Market", "Auchan", "dm", "Rossmann"];

function rememberedShop(): string {
  try {
    return localStorage.getItem(SHOP_KEY) ?? "";
  } catch {
    return ""; // private windows and blocked site data both throw here
  }
}

type Pending = { name: string; state: "uploading" | "done" | "failed"; detail?: string };

export default function Labels() {
  const [shop, setShop] = useState(rememberedShop);
  const [pending, setPending] = useState<Pending[]>([]);
  const [reload, setReload] = useState(0);
  const photos = useAsync(() => api.labelPhotos(30), [reload]);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    try {
      if (shop) localStorage.setItem(SHOP_KEY, shop);
    } catch {
      /* remembering the shop is a convenience, not a requirement */
    }
  }, [shop]);

  async function send(files: FileList | null) {
    if (!files?.length) return;
    const chosen = Array.from(files);
    setPending((current) => [
      ...chosen.map((file) => ({ name: file.name, state: "uploading" as const })),
      ...current,
    ]);

    // One request per photo, sequentially. A shelf strip and the next shelf along are
    // unrelated, so there is nothing to gain by sending them together - and plenty to lose
    // if a dropped connection takes all six with it.
    for (const file of chosen) {
      try {
        await api.uploadLabel(file, shop.trim() || null);
        setPending((c) => c.map((p) => (p.name === file.name ? { ...p, state: "done" } : p)));
      } catch (err) {
        setPending((c) =>
          c.map((p) =>
            p.name === file.name
              ? { ...p, state: "failed", detail: (err as Error).message }
              : p,
          ),
        );
      }
    }
    setReload((n) => n + 1);
  }

  return (
    <>
      <div className="row page-actions" style={{ marginBottom: 14 }}>
        <h1 style={{ flex: 1 }}>Árcímkék</h1>
        <Link className="btn" to="/">← Fotózás</Link>
      </div>

      <Card>
        <p className="muted" style={{ marginTop: 0 }}>
          Fotózd le a polccímkét, és az ár bekerül az ártörténetbe – anélkül, hogy megvennéd.
          Ez <strong>nem</strong> kiadás: a havi összegedhez soha nem adódik hozzá.
        </p>

        <label>
          Melyik boltban vagy?
          <input
            value={shop}
            onChange={(event) => setShop(event.target.value)}
            placeholder="pl. Aldi"
            autoComplete="off"
          />
        </label>
        <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 8 }}>
          {COMMON_SHOPS.map((name) => (
            <button
              key={name}
              className={`btn${shop === name ? " primary" : ""}`}
              onClick={() => setShop(name)}
            >
              {name}
            </button>
          ))}
        </div>
        <p className="muted" style={{ fontSize: "0.82rem", marginBottom: 0 }}>
          A címkén általában nincs rajta a bolt neve, ezért egyszer kérdezzük meg – utána a
          látogatás végéig ez marad.
        </p>
      </Card>

      <Card>
        <input
          ref={input}
          type="file"
          accept="image/*"
          capture="environment"
          multiple
          hidden
          onChange={(event) => {
            send(event.target.files);
            event.target.value = ""; // so the same photo can be retaken
          }}
        />
        <button
          className="btn primary big"
          style={{ width: "100%" }}
          disabled={!shop.trim()}
          onClick={() => input.current?.click()}
        >
          📷 Címke fotózása
        </button>
        {!shop.trim() && (
          <p className="muted" style={{ fontSize: "0.84rem", marginBottom: 0 }}>
            Előbb add meg a boltot – ár bolt nélkül nem összehasonlítható semmivel.
          </p>
        )}
        <p className="muted" style={{ fontSize: "0.84rem", marginBottom: 0 }}>
          Egy képen több címke is lehet – egy polccsík hat terméket is jelenthet.
        </p>

        {pending.length > 0 && (
          <ul className="muted" style={{ fontSize: "0.86rem", paddingLeft: 18 }}>
            {pending.slice(0, 8).map((item, index) => (
              <li key={`${item.name}-${index}`}>
                {item.state === "uploading" && "Feltöltés… "}
                {item.state === "done" && "✓ "}
                {item.state === "failed" && "✗ "}
                {item.name}
                {item.detail && <span className="error"> – {item.detail}</span>}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <AsyncBlock state={photos} empty="Még nincs lefotózott címke.">
        {(rows) => (
          <Card
            title="Legutóbbi címkék"
            action={
              <button className="btn" onClick={() => setReload((n) => n + 1)}>Frissítés</button>
            }
          >
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Mikor</th>
                    <th>Bolt</th>
                    <th className="num">Címke</th>
                    <th>Állapot</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((photo) => (
                    <tr key={photo.id}>
                      <td>{new Date(photo.observed_at).toLocaleString("hu-HU")}</td>
                      <td>{photo.merchant_name ?? <span className="muted">ismeretlen</span>}</td>
                      <td className="num">{photo.observation_count}</td>
                      <td><Status photo={photo} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </AsyncBlock>
    </>
  );
}

const LABEL: Record<string, { text: string; className: string }> = {
  pending: { text: "Sorban", className: "" },
  processing: { text: "Olvasás…", className: "" },
  parsed: { text: "Kész", className: "good" },
  needs_review: { text: "Ellenőrzendő", className: "warn" },
  failed: { text: "Hiba", className: "bad" },
  confirmed: { text: "Megerősítve", className: "good" },
};

function Status({ photo }: { photo: LabelPhoto }) {
  const label = LABEL[photo.status] ?? { text: photo.status, className: "" };
  return (
    <>
      <span className={`badge ${label.className}`}>{label.text}</span>
      {photo.error && (
        <div className="muted" style={{ fontSize: "0.78rem" }}>{photo.error}</div>
      )}
    </>
  );
}