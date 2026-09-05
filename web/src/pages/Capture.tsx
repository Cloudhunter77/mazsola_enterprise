/** The capture screen.
 *
 *  `capture="environment"` on a file input opens the rear camera directly on both iOS and
 *  Android with no native app and no permissions dance. A second input without that
 *  attribute opens the photo library instead - the same element, and the attribute is the
 *  only difference, which is why there are two inputs rather than one with a mode flag.
 *
 *  Both accept several files. A receipt longer than a phone frame can hold legibly is
 *  photographed in overlapping sections and uploaded together as one receipt; the sections
 *  are read as a single document. After upload the page polls until the worker finishes, so
 *  you see what was read while you are still standing in the shop and can retake a bad shot.
 */

import { type ChangeEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, type ReceiptDetail } from "../lib/api";
import { KIND_LABELS, REVIEW_REASONS, ft, dateTime } from "../lib/format";
import { Card } from "../components/ui";

type Phase = "idle" | "uploading" | "waiting" | "done" | "error";

const TERMINAL = new Set(["parsed", "needs_review", "failed", "confirmed"]);

// Matches MAX_PARTS in app/services/ingest.py. Exceeding it is refused server-side; this
// only saves the round trip.
const MAX_PARTS = 8;

type Part = { file: File; preview: string };

export default function Capture() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<ReceiptDetail | null>(null);
  const [parts, setParts] = useState<Part[]>([]);
  const cameraInput = useRef<HTMLInputElement>(null);
  const galleryInput = useRef<HTMLInputElement>(null);
  const pollTimer = useRef<number | null>(null);

  // Object URLs are revoked explicitly wherever parts are dropped, so this only has to
  // catch the case of leaving the page mid-flow.
  const partsRef = useRef<Part[]>([]);
  partsRef.current = parts;
  useEffect(() => () => {
    if (pollTimer.current) window.clearTimeout(pollTimer.current);
    for (const part of partsRef.current) URL.revokeObjectURL(part.preview);
  }, []);

  const poll = useCallback((id: string, attempt = 0) => {
    api.receipt(id)
      .then((detail) => {
        setReceipt(detail);
        if (TERMINAL.has(detail.status)) {
          setPhase("done");
          return;
        }
        if (attempt > 60) {
          setPhase("error");
          setMessage("A feldolgozás szokatlanul sokáig tart. Nézd meg a Blokkok között.");
          return;
        }
        pollTimer.current = window.setTimeout(() => poll(id, attempt + 1), 2000);
      })
      .catch((err: Error) => { setPhase("error"); setMessage(err.message); });
  }, []);

  function onPick(event: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(event.target.files ?? []);
    // Reset the input first, so picking the same photo again after a retake still fires.
    event.target.value = "";
    if (!picked.length) return;

    setMessage(null);
    setParts((current) => {
      const room = MAX_PARTS - current.length;
      if (picked.length > room) {
        setMessage(`Egy blokk legfeljebb ${MAX_PARTS} képből állhat.`);
      }
      const added = picked.slice(0, Math.max(room, 0)).map((file) => ({
        file,
        preview: URL.createObjectURL(file),
      }));
      return [...current, ...added];
    });
  }

  function removePart(index: number) {
    setParts((current) => {
      URL.revokeObjectURL(current[index].preview);
      return current.filter((_, i) => i !== index);
    });
  }

  async function send() {
    if (!parts.length) return;
    setPhase("uploading");
    setProgress(0);
    setMessage(null);
    setReceipt(null);

    try {
      const response = await api.upload(parts.map((part) => part.file), setProgress);
      if (response.duplicate) {
        setMessage("Ezt már feltöltötted – ugyanazt a blokkot mutatom.");
      }
      setPhase("waiting");
      poll(response.id);
    } catch (err) {
      setPhase("error");
      setMessage((err as Error).message);
    }
  }

  function reset() {
    if (pollTimer.current) window.clearTimeout(pollTimer.current);
    for (const part of parts) URL.revokeObjectURL(part.preview);
    setParts([]);
    setReceipt(null);
    setMessage(null);
    setPhase("idle");
  }

  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Blokk rögzítése</h1>

      {/* Two inputs, differing only in `capture`: with it the rear camera opens directly,
          without it the photo library does. `multiple` lets a long receipt be captured in
          overlapping sections. */}
      <input
        ref={cameraInput}
        type="file"
        accept="image/*"
        capture="environment"
        multiple
        onChange={onPick}
        style={{ display: "none" }}
      />
      <input
        ref={galleryInput}
        type="file"
        accept="image/*"
        multiple
        onChange={onPick}
        style={{ display: "none" }}
      />

      {phase === "idle" && (
        <Card>
          <p className="muted" style={{ marginTop: 0 }}>
            Fotózd le a blokkot fentről lefelé, lehetőleg sima felületen. A többi megy magától.
          </p>

          {parts.length > 0 && <PartStrip parts={parts} onRemove={removePart} />}

          <div className="row" style={{ gap: 8 }}>
            <button
              className="btn primary big"
              style={{ flex: 1 }}
              onClick={() => cameraInput.current?.click()}
            >
              📷 {parts.length ? "További rész" : "Fotó készítése"}
            </button>
            <button
              className="btn big"
              style={{ flex: 1 }}
              onClick={() => galleryInput.current?.click()}
            >
              🖼️ Tallózás
            </button>
          </div>

          {parts.length > 0 && (
            <button
              className="btn primary big"
              style={{ width: "100%", marginTop: 8 }}
              onClick={send}
            >
              Feldolgozás ({parts.length} kép)
            </button>
          )}

          {message && <p className="error" style={{ marginBottom: 0 }}>{message}</p>}

          <p className="muted" style={{ fontSize: "0.84rem", marginBottom: 0 }}>
            Hosszú blokknál fotózd több részletben, felülről lefelé haladva, és hagyj pár sor
            átfedést a részek között – így az apró betű is olvasható marad. Egy blokként
            dolgozom fel őket.
          </p>
        </Card>
      )}

      {phase !== "idle" && (
        <Card
          title={
            phase === "uploading" ? "Feltöltés…"
              : phase === "waiting" ? "Felismerés folyamatban…"
              : phase === "error" ? "Hiba"
              : "Kész"
          }
          action={
            <button className="btn" onClick={reset}>Új blokk</button>
          }
        >
          <div className="row" style={{ alignItems: "flex-start", gap: 16 }}>
            {parts.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {parts.map((part, index) => (
                  <img
                    key={part.preview}
                    src={part.preview}
                    alt={`A feltöltött blokk ${index + 1}. része`}
                    style={{ width: 130, borderRadius: 8, border: "1px solid var(--border)" }}
                  />
                ))}
              </div>
            )}
            <div style={{ flex: 1, minWidth: 220 }}>
              {phase === "uploading" && (
                <p className="muted">{Math.round(progress * 100)}% feltöltve</p>
              )}
              {phase === "waiting" && (
                <p className="muted">
                  <span className="spinner" aria-hidden />{" "}
                  <span style={{ marginLeft: 8 }}>A blokk olvasása…</span>
                </p>
              )}
              {message && <p className={phase === "error" ? "error" : "muted"}>{message}</p>}
              {receipt && phase === "done" && <Result receipt={receipt} />}
            </div>
          </div>
        </Card>
      )}
    </>
  );
}

function PartStrip({ parts, onRemove }: { parts: Part[]; onRemove: (index: number) => void }) {
  return (
    <div className="row" style={{ gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
      {parts.map((part, index) => (
        <div key={part.preview} style={{ position: "relative" }}>
          <img
            src={part.preview}
            alt={`${index + 1}. rész`}
            style={{
              width: 76, height: 100, objectFit: "cover",
              borderRadius: 8, border: "1px solid var(--border)",
            }}
          />
          <span
            className="badge"
            style={{ position: "absolute", left: 4, bottom: 4, fontSize: "0.7rem" }}
          >
            {index + 1}
          </span>
          <button
            className="btn"
            aria-label={`${index + 1}. rész eltávolítása`}
            onClick={() => onRemove(index)}
            style={{
              position: "absolute", top: -6, right: -6,
              padding: "0 7px", lineHeight: "20px", borderRadius: "50%",
            }}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

function Result({ receipt }: { receipt: ReceiptDetail }) {
  if (receipt.status === "failed") {
    return (
      <>
        <p className="error">Nem sikerült feldolgozni: {receipt.error}</p>
        <Link className="btn" to={`/blokkok/${receipt.id}`}>Megnyitás</Link>
      </>
    );
  }

  const goods = receipt.items.filter((item) => item.kind === "item");

  return (
    <>
      <div style={{ fontSize: "1.5rem", fontWeight: 680 }}>{ft(receipt.total_gross)}</div>
      <div className="muted" style={{ marginBottom: 10 }}>
        {receipt.merchant_name ?? "Ismeretlen bolt"} · {dateTime(receipt.purchased_at)} ·{" "}
        {goods.length} tétel
      </div>

      {receipt.review_reasons?.length ? (
        <div style={{ marginBottom: 10 }}>
          <span className="badge warn">⚠ Ellenőrzendő</span>
          <ul className="muted" style={{ margin: "6px 0 0", paddingLeft: 20, fontSize: "0.84rem" }}>
            {receipt.review_reasons.map((reason) => (
              <li key={reason}>{REVIEW_REASONS[reason] ?? reason}</li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="badge good" style={{ marginBottom: 10 }}>✓ Az összegek stimmelnek</p>
      )}

      <div className="table-wrap" style={{ maxHeight: 220, overflowY: "auto" }}>
        <table>
          <tbody>
            {receipt.items.map((item) => (
              <tr key={item.id}>
                <td>
                  {item.raw_name}
                  {item.kind !== "item" && (
                    <span className="muted"> · {KIND_LABELS[item.kind] ?? item.kind}</span>
                  )}
                </td>
                <td className="num">{ft(item.gross_amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="row" style={{ marginTop: 12 }}>
        <Link className="btn primary" to={`/blokkok/${receipt.id}`}>Megnyitás és ellenőrzés</Link>
      </div>
    </>
  );
}
