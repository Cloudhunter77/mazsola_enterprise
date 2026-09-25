/** Every price read off a shelf label, whether or not it belongs to a product yet.
 *
 *  This used to live at the bottom of the label camera screen, which is where you are
 *  when you take the photos and nowhere near where you look when you want to know what
 *  something costs. It sits under Árak now, beside the price history it feeds.
 *
 *  A shelf price is what a shop asked, never what you paid, so nothing here reaches your
 *  spending. Once a label resolves to a tracked product its price also joins that
 *  product's history, marked as a shelf price; this list keeps the ones that do not
 *  resolve too, so no reading is ever out of sight.
 */

import { Fragment, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { ft } from "../lib/format";
import { AsyncBlock, Card, useAsync, useLive } from "../components/ui";

export default function ShelfPrices() {
  const prices = useAsync(() => api.scannedPrices(200), []);
  // New labels are read in the background; refreshing on focus is enough to pick them up.
  useLive(prices, () => false);
  // Which photo is open beneath the table. The label is only half of what the picture holds:
  // the product itself is usually in frame behind it, which is the reason for keeping it.
  const [openPhoto, setOpenPhoto] = useState<string | null>(null);

  return (
    <>
      <div className="row page-actions" style={{ marginBottom: 14 }}>
        <h1 style={{ flex: 1 }}>Polcárak</h1>
        <Link className="btn" to="/arcimkek">📷 Új címke</Link>
      </div>

      <AsyncBlock
        state={prices}
        empty="Még nincs beolvasott ár. A Rögzítés → Árcímke fülön fotózhatsz polccímkét."
      >
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

    </>
  );
}
