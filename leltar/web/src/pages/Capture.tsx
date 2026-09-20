import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, type UploadResponse } from "../lib/api";
import { AsyncBlock, Card, useAsync } from "../components/ui";

/** Photograph things, say where they are, and hand them to the worker.
 *
 *  The place is chosen *before* the photo rather than asked for afterwards: it is the one
 *  fact a photograph cannot carry and you always know while standing in the room. It is
 *  remembered between uploads, because cataloguing a room is a dozen photographs in a row
 *  and re-picking "Garázs" each time would be the most tedious part of the app.
 */
export default function Capture() {
  const places = useAsync(() => api.places(), []);
  const [placeId, setPlaceId] = useState<string>(() => {
    try {
      return localStorage.getItem("leltar-last-place") ?? "";
    } catch {
      return ""; // private windows and blocked site data both throw here
    }
  });
  const [progress, setProgress] = useState<number | null>(null);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  function rememberPlace(value: string) {
    setPlaceId(value);
    try {
      localStorage.setItem("leltar-last-place", value);
    } catch {
      /* remembering the room is a convenience, not a requirement */
    }
  }

  async function upload(files: FileList | null) {
    if (!files || files.length === 0) return;
    setError(null);
    setResult(null);
    setProgress(0);
    try {
      const response = await api.upload(Array.from(files), placeId || null, setProgress);
      setResult(response);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setProgress(null);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <>
      <Card title="Mit fényképezel?">
        <AsyncBlock state={places}>
          {(rows) => (
            <label className="field">
              Hely
              <select value={placeId} onChange={(event) => rememberPlace(event.target.value)}>
                <option value="">— nincs megadva —</option>
                {rows.map((place) => (
                  <option key={place.id} value={place.id}>{place.path}</option>
                ))}
              </select>
            </label>
          )}
        </AsyncBlock>
        <p className="card-note">
          A gép ezt kontextusként kapja meg, és minden felismert tárgy ide kerül.
        </p>
      </Card>

      <Card>
        <label className="capture">
          <span className="glyph" aria-hidden>📷</span>
          <strong>Fénykép készítése vagy kiválasztása</strong>
          <span className="muted">
            Egy polcról készült kép is jó: több tárgyat is felismer egyszerre.
          </span>
          <input
            ref={input}
            type="file"
            accept="image/*"
            multiple
            style={{ display: "none" }}
            onChange={(event) => upload(event.target.files)}
          />
        </label>

        {progress !== null && (
          <p className="muted" style={{ marginTop: 12 }}>
            <span className="spinner" aria-hidden /> Feltöltés… {Math.round(progress * 100)}%
          </p>
        )}
        {error && <p className="error" style={{ marginTop: 12 }}>{error}</p>}

        {result && (
          <div style={{ marginTop: 14 }}>
            <p>
              {result.queued > 0 && <strong>{result.queued} fénykép sorban áll. </strong>}
              {result.duplicates > 0 && (
                <span className="muted">
                  {result.duplicates} már korábban feltöltött kép volt, azt nem olvassuk el újra.
                </span>
              )}
            </p>
            <div className="row">
              <button className="btn primary" onClick={() => navigate("/ellenorzes")}>
                Ellenőrzés
              </button>
              {result.photos[0] && (
                <button
                  className="btn"
                  onClick={() => navigate(`/fenykep/${result.photos[0].id}`)}
                >
                  Az első kép megnyitása
                </button>
              )}
            </div>
          </div>
        )}
      </Card>
    </>
  );
}
