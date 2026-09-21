import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, type StatsSummary, type UploadResponse } from "../lib/api";
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
  // Remembered like the place, for the same reason: cataloguing is a run of photographs
  // of the same kind, and re-choosing on every one is what makes people stop.
  const [mode, setMode] = useState<"scene" | "single">(() => {
    try {
      return (localStorage.getItem("leltar-mode") as "scene" | "single") ?? "single";
    } catch {
      return "single";
    }
  });
  const [progress, setProgress] = useState<number | null>(null);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [queue, setQueue] = useState<StatsSummary | null>(null);
  const camera = useRef<HTMLInputElement>(null);
  const gallery = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  // How far ahead of the other person you are. When one of you photographs and the other
  // approves names, this is the only thing on the capture screen that tells you whether
  // to keep walking or to go and help - and it is why the photographer does not need to
  // ask out loud.
  useEffect(() => {
    const refresh = () => {
      if (document.hidden) return;
      api.summary().then(setQueue).catch(() => undefined);
    };
    refresh();
    const timer = setInterval(refresh, 8000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [progress, result]);

  function rememberPlace(value: string) {
    setPlaceId(value);
    try {
      localStorage.setItem("leltar-last-place", value);
    } catch {
      /* remembering the room is a convenience, not a requirement */
    }
  }

  function rememberMode(value: "scene" | "single") {
    setMode(value);
    try {
      localStorage.setItem("leltar-mode", value);
    } catch {
      /* a convenience, not a requirement */
    }
  }

  async function upload(files: FileList | null) {
    if (!files || files.length === 0) return;
    setError(null);
    setResult(null);
    setProgress(0);
    try {
      const response = await api.upload(Array.from(files), placeId || null, mode, setProgress);
      setResult(response);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setProgress(null);
      // Both are cleared, whichever was used: without it, photographing the same thing
      // twice in a row fires no change event the second time and nothing happens.
      if (camera.current) camera.current.value = "";
      if (gallery.current) gallery.current.value = "";
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

        <div className="modes" style={{ marginTop: 12 }}>
          <button
            className={mode === "single" ? "on" : ""}
            onClick={() => rememberMode("single")}
            aria-pressed={mode === "single"}
          >
            Egy tárgy
            <small>a képen egy dolog van</small>
          </button>
          <button
            className={mode === "scene" ? "on" : ""}
            onClick={() => rememberMode("scene")}
            aria-pressed={mode === "scene"}
          >
            Polc, szoba
            <small>több tárgyat is felismer</small>
          </button>
        </div>
      </Card>

      <Card>
        {/* Two inputs, not one with a choice inside it. `capture` is what sends a phone
            straight to its camera instead of a file picker, and a browser that honours it
            ignores `multiple` - one press, one photograph. So the camera and the gallery
            are separate controls, and the gallery keeps the multi-select that makes
            emptying a morning's photographs into the app one action.

            This route needs no HTTPS: it hands off to the phone's own camera app rather
            than opening a video stream in the page, which is what getUserMedia would do
            and what a NAS reached over plain HTTP on a VPN could not offer. */}
        <label className="capture">
          <span className="glyph" aria-hidden>📷</span>
          <strong>Fénykép készítése</strong>
          <span className="muted">
            {mode === "single"
              ? "Egy tárgyról készült kép: a gép a főszereplőt nevezi meg, nem az asztalt alatta."
              : "Egy polcról készült kép: minden tárgyat felismer, és mindegyikhez kivág egy képet."}
          </span>
          <input
            ref={camera}
            type="file"
            accept="image/*"
            capture="environment"
            style={{ display: "none" }}
            onChange={(event) => upload(event.target.files)}
          />
        </label>

        <label className="btn block" style={{ marginTop: 10 }}>
          🖼️ Tallózás a galériában
          <input
            ref={gallery}
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

        {queue && (queue.photos_pending > 0 || queue.photos_needing_review > 0) && (
          <p className="card-note" style={{ marginTop: 12 }}>
            {queue.photos_pending > 0 && <>🔄 {queue.photos_pending} kép beolvasás alatt</>}
            {queue.photos_pending > 0 && queue.photos_needing_review > 0 && " · "}
            {queue.photos_needing_review > 0 && (
              <>✅ {queue.photos_needing_review} vár ellenőrzésre</>
            )}
          </p>
        )}

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
