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

import { Fragment, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, type LabelPhoto } from "../lib/api";
import { ft } from "../lib/format";
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
  // Which photo is open beneath the table. The label is only half of what the picture holds:
  // the product itself is usually in frame behind it, which is the reason for keeping it.
  const [openPhoto, setOpenPhoto] = useState<string | null>(null);
  const photos = useAsync(() => api.labelPhotos(30), [reload]);
  const prices = useAsync(() => api.scannedPrices(200), [reload]);
  const cameraInput = useRef<HTMLInputElement>(null);
  const galleryInput = useRef<HTMLInputElement>(null);

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
        {/* Two inputs differing only in `capture`: with it the rear camera opens directly,
            without it the photo library does. Labels taken earlier are as good a price
            record as ones taken now - the date that matters is when the photo was taken,
            and that is what the file carries. */}
        <input
          ref={cameraInput}
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
        <input
          ref={galleryInput}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={(event) => {
            send(event.target.files);
            event.target.value = "";
          }}
        />

        <div className="row" style={{ gap: 8 }}>
          <button
            className="btn primary big"
            style={{ flex: 1 }}
            disabled={!shop.trim()}
            onClick={() => cameraInput.current?.click()}
          >
            📷 Fotózás
          </button>
          <button
            className="btn big"
            style={{ flex: 1 }}
            disabled={!shop.trim()}
            onClick={() => galleryInput.current?.click()}
          >
            🖼️ Tallózás
          </button>
        </div>
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

      <AsyncBlock state={prices} empty="Még nincs beolvasott ár.">
        {(rows) => (
          <Card title="Beolvasott árak" note={`${rows.length} ár`}>
            <p className="muted" style={{ marginTop: 0, fontSize: "0.86rem" }}>
              Amit a polcon láttál. Ha a termék már ismert, az ár bekerül az{" "}
              <Link to="/arak">ártörténetbe</Link> is – de itt akkor is megvan, ha még nincs
              hozzá termék.
            </p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Megnevezés</th>
                    <th className="num">Ár</th>
                    <th className="num">Egységár</th>
                    <th>Bolt</th>
                    <th>Mikor</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <Fragment key={row.id}>
                    <tr>
                      <td>
                        {row.raw_name}
                        {row.product_name && (
                          <div className="muted" style={{ fontSize: "0.78rem" }}>
                            → {row.product_name}
                          </div>
                        )}
                      </td>
                      <td className="num">
                        {row.price == null ? "–" : ft(row.price)}
                        {row.is_promotion && (
                          <div>
                            <span className="badge warn">akció</span>
                            {row.regular_price && (
                              <span
                                className="muted"
                                style={{ fontSize: "0.76rem", textDecoration: "line-through" }}
                              >
                                {" "}{ft(row.regular_price)}
                              </span>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="num">
                        {row.unit_price == null
                          ? "–"
                          : `${ft(row.unit_price)}/${row.unit ?? "?"}`}
                      </td>
                      <td>{row.merchant_name ?? <span className="muted">?</span>}</td>
                      <td>{new Date(row.observed_at).toLocaleDateString("hu-HU")}</td>
                      <td className="num" style={{ whiteSpace: "nowrap" }}>
                        <button
                          className="btn"
                          aria-label={`${row.raw_name} a listára`}
                          title="Fel a bevásárlólistára"
                          onClick={() =>
                            api
                              .addToList(
                                row.product_id
                                  ? { product_id: row.product_id }
                                  : { raw_name: row.raw_name },
                              )
                              .catch(() => undefined)
                          }
                        >
                          🛒
                        </button>{" "}
                        <button
                          className="btn"
                          aria-label="A címke fotója"
                          onClick={() =>
                            setOpenPhoto(openPhoto === row.photo_id ? null : row.photo_id)
                          }
                        >
                          {openPhoto === row.photo_id ? "✕" : "🔍"}
                        </button>
                      </td>
                    </tr>
                    {openPhoto === row.photo_id && (
                      <tr>
                        <td colSpan={6} style={{ padding: 0 }}>
                          <a
                            href={api.labelImageUrl(row.photo_id)}
                            target="_blank"
                            rel="noreferrer"
                            title="Megnyitás teljes méretben"
                          >
                            <img
                              src={api.labelImageUrl(row.photo_id)}
                              alt="A polccímke fotója"
                              style={{
                                display: "block",
                                width: "100%",
                                maxHeight: "70vh",
                                objectFit: "contain",
                                background: "var(--grid)",
                              }}
                            />
                          </a>
                          <p className="muted" style={{ fontSize: "0.8rem", margin: "6px 0" }}>
                            Koppints a képre a teljes méretért. Az eredeti fotó van eltárolva,
                            nem a kicsinyített másolat – a termék is látszik rajta.
                          </p>
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </AsyncBlock>

      <AsyncBlock state={photos} empty="Még nincs lefotózott címke.">
        {(rows) => (
          <Card
            title="Beolvasott fotók"
            action={
              <button className="btn" onClick={() => setReload((n) => n + 1)}>Frissítés</button>
            }
          >
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th />
                    <th>Mikor</th>
                    <th>Bolt</th>
                    <th className="num">Címke</th>
                    <th>Állapot</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((photo) => (
                    <tr key={photo.id}>
                      <td style={{ width: 56 }}>
                        <a
                          href={api.labelImageUrl(photo.id)}
                          target="_blank"
                          rel="noreferrer"
                          title="A fotó megnyitása"
                        >
                          <img
                            src={api.labelImageUrl(photo.id)}
                            alt=""
                            loading="lazy"
                            style={{
                              width: 48,
                              height: 48,
                              objectFit: "cover",
                              borderRadius: 6,
                              background: "var(--grid)",
                            }}
                          />
                        </a>
                      </td>
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