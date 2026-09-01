/** The capture screen.
 *
 *  `capture="environment"` on a file input opens the rear camera directly on both iOS and
 *  Android with no native app and no permissions dance - which is why this is the whole
 *  capture story. After upload the page polls the receipt until the worker finishes, so
 *  you see what was read while you are still standing in the shop and can retake a bad shot.
 */

import { type ChangeEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, type ReceiptDetail } from "../lib/api";
import { KIND_LABELS, REVIEW_REASONS, ft, dateTime } from "../lib/format";
import { Card } from "../components/ui";

type Phase = "idle" | "uploading" | "waiting" | "done" | "error";

const TERMINAL = new Set(["parsed", "needs_review", "failed", "confirmed"]);

export default function Capture() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<ReceiptDetail | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const pollTimer = useRef<number | null>(null);

  useEffect(() => () => {
    if (pollTimer.current) window.clearTimeout(pollTimer.current);
    if (preview) URL.revokeObjectURL(preview);
  }, [preview]);

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

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;

    if (preview) URL.revokeObjectURL(preview);
    setPreview(URL.createObjectURL(file));
    setPhase("uploading");
    setProgress(0);
    setMessage(null);
    setReceipt(null);

    try {
      const response = await api.upload(file, setProgress);
      if (response.duplicate) setMessage("Ezt a képet már feltöltötted – ugyanazt a blokkot mutatom.");
      setPhase("waiting");
      poll(response.id);
    } catch (err) {
      setPhase("error");
      setMessage((err as Error).message);
    } finally {
      // Let the same photo be picked again after a retake.
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  function reset() {
    if (pollTimer.current) window.clearTimeout(pollTimer.current);
    if (preview) URL.revokeObjectURL(preview);
    setPreview(null);
    setReceipt(null);
    setMessage(null);
    setPhase("idle");
  }

  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Blokk rögzítése</h1>

      <input
        ref={fileInput}
        type="file"
        accept="image/*"
        capture="environment"
        onChange={onFile}
        style={{ display: "none" }}
      />

      {phase === "idle" && (
        <Card>
          <p className="muted" style={{ marginTop: 0 }}>
            Fotózd le a blokkot fentről lefelé, lehetőleg sima felületen. A többi megy magától.
          </p>
          <button
            className="btn primary big"
            style={{ width: "100%" }}
            onClick={() => fileInput.current?.click()}
          >
            📷 Fotó készítése
          </button>
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
            {preview && (
              <img
                src={preview}
                alt="A feltöltött blokk"
                style={{ width: 130, borderRadius: 8, border: "1px solid var(--border)" }}
              />
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
