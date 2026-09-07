/** Rendszer: which build is running, and did the migrations finish.
 *
 *  This page exists so updating never needs a shell. Pulling the image is a menu item in
 *  the TrueNAS Apps screen; the part that used to need SSH was proving the pull took -
 *  comparing image digests and reading container logs. The commit and the schema state are
 *  here instead, and the one line that matters is whether the schema is up to date.
 */

import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { dateTime } from "../lib/format";
import { AsyncBlock, Card, Tile, useAsync } from "../components/ui";

const REPO = "https://github.com/Cloudhunter77/mazsola_enterprise";

export default function System() {
  const info = useAsync(() => api.system(), []);

  return (
    <>
      <div className="row" style={{ marginBottom: 14 }}>
        <h1 style={{ flex: 1 }}>Rendszer</h1>
        <Link className="btn" to="/tabla">← Tábla</Link>
      </div>

      <AsyncBlock state={info}>
        {(data) => (
          <>
            <Card title="Ez a verzió fut">
              <table>
                <tbody>
                  <Row label="Verzió" value={data.version} mono />
                  <Row
                    label="Commit"
                    mono
                    value={
                      data.build.commit ? (
                        <a
                          href={`${REPO}/commit/${data.build.commit}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {data.build.commit.slice(0, 12)}
                        </a>
                      ) : "forrásból fut (nincs bélyegzve)"
                    }
                  />
                  <Row
                    label="Build ideje"
                    value={data.build.built_at ? dateTime(data.build.built_at) : "–"}
                  />
                  <Row label="Motor" value={`${data.extractor} · ${data.model ?? "–"}`} mono />
                  <Row
                    label="Feldolgozó"
                    value={data.worker_enabled ? "✓ fut" : "⚠ ki van kapcsolva"}
                  />
                  <Row
                    label="Képméret"
                    value={`max ${data.max_image_edge} px, min szélesség ${data.min_image_width} px`}
                  />
                </tbody>
              </table>

              <p className="muted" style={{ fontSize: "0.84rem", marginBottom: 0 }}>
                Frissítés után ezt a commitot hasonlítsd össze a repóban lévő legutóbbival.
                Ha egyezik, a pull sikerült – nem kell shellbe lépni hozzá.
              </p>
            </Card>

            <Card title="Adatbázis">
              {data.schema.up_to_date ? (
                <p className="badge good">✓ Az adatbázis séma naprakész</p>
              ) : (
                <p className="badge warn">
                  ⚠ A séma nem naprakész – a migráció nem futott le
                </p>
              )}
              <table>
                <tbody>
                  <Row label="Kód szerint" value={data.schema.expected ?? "–"} mono />
                  <Row label="Adatbázisban" value={data.schema.applied ?? "–"} mono />
                </tbody>
              </table>
              {!data.schema.up_to_date && (
                <p className="muted" style={{ marginBottom: 0 }}>
                  Indítsd újra az appot a TrueNAS Apps fülön. A migráció induláskor fut le, és
                  amíg nem sikerül, az app nem szolgál ki kérést – ha ez az oldal betöltött,
                  a séma szinte biztosan rendben van.
                </p>
              )}
            </Card>

            <Card title="Blokkok">
              <div className="grid tiles">
                <Tile label="Összesen" value={data.receipts.total} />
                <Tile label="Sorban áll" value={data.receipts.pending} />
                <Tile label="Ellenőrzendő" value={data.receipts.needs_review} />
                <Tile label="Sikertelen" value={data.receipts.failed} />
              </div>
              {data.receipts.pending > 0 && !data.worker_enabled && (
                <p className="error" style={{ marginBottom: 0 }}>
                  Van várakozó blokk, de a feldolgozó ki van kapcsolva – állítsd a{" "}
                  <code>WORKER_ENABLED</code> értékét <code>true</code>-ra.
                </p>
              )}
            </Card>
          </>
        )}
      </AsyncBlock>
    </>
  );
}

function Row({ label, value, mono }: {
  label: string; value: ReactNode; mono?: boolean;
}) {
  return (
    <tr>
      <td className="muted" style={{ whiteSpace: "nowrap" }}>{label}</td>
      <td className={mono ? "mono" : undefined}>{value}</td>
    </tr>
  );
}
