/** Javítani való: what to change in the app, written down while you are using it.
 *
 *  The moment you notice something - a misread total, a button that is hard to hit - is
 *  the moment a separate notes app is not open. So it goes here, with a picture if a
 *  screenshot says it better: on a phone the picker offers the camera or the gallery, and
 *  on a computer a screenshot can be pasted straight into the text box.
 *
 *  "Másolás" copies the open notes as plain text, ready to paste wherever the changes are
 *  being asked for. Done notes are kept, folded away, so "did we ever fix that?" has an
 *  answer.
 */

import { type ClipboardEvent, type FormEvent, useEffect, useRef, useState } from "react";

import { api, type FixNote } from "../lib/api";
import { date } from "../lib/format";
import { AsyncBlock, Card, useAsync } from "./ui";

export default function FixNotes() {
  const [reload, setReload] = useState(0);
  const notes = useAsync(() => api.fixNotes(), [reload]);
  const [adding, setAdding] = useState(false);
  const [copied, setCopied] = useState(false);
  const refresh = () => setReload((n) => n + 1);

  const open = (notes.data ?? []).filter((note) => !note.done);

  async function copy() {
    const text = open
      .map((note, index) =>
        `${index + 1}. ${note.text || "(csak kép)"}` +
        `${note.has_image ? " [kép csatolva]" : ""} – ${note.created_by ?? "?"}, ${date(note.created_at)}`,
      )
      .join("\n");
    try {
      await navigator.clipboard.writeText(`Javítani való (${open.length})\n\n${text}`);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access needs a secure page; over plain HTTP on the LAN it can be refused.
      window.prompt("Másold ki innen:", text);
    }
  }

  return (
    <Card
      title="Javítani való"
      note={notes.data ? `${open.length} nyitott` : undefined}
      action={
        open.length > 0 ? (
          <button className="btn" onClick={copy}>{copied ? "✓ Kimásolva" : "Másolás"}</button>
        ) : undefined
      }
    >
      {adding ? (
        <NewNote onDone={() => { setAdding(false); refresh(); }} onCancel={() => setAdding(false)} />
      ) : (
        <button className="btn primary block" onClick={() => setAdding(true)}>
          + Új javítani való
        </button>
      )}

      <AsyncBlock state={notes} empty="">
        {(rows) => <NoteList rows={rows} onChange={refresh} />}
      </AsyncBlock>
    </Card>
  );
}

function NewNote({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [text, setText] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!image) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(image);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [image]);

  // A screenshot on the clipboard pastes straight in, the way it would into a chat.
  function paste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const file = Array.from(event.clipboardData.files).find((f) => f.type.startsWith("image/"));
    if (file) {
      event.preventDefault();
      setImage(file);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.addFixNote(text.trim(), image);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <textarea
        autoFocus
        rows={4}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onPaste={paste}
        placeholder="Mi nem jó, vagy mit kellene másképp?"
        style={{ width: "100%", resize: "vertical" }}
        aria-label="Javítani való leírása"
      />
      <input
        ref={picker}
        type="file"
        accept="image/*"
        hidden
        onChange={(event) => {
          setImage(event.target.files?.[0] ?? null);
          event.target.value = "";
        }}
      />
      {preview ? (
        <div className="row" style={{ gap: 10, alignItems: "center", margin: "8px 0" }}>
          <img src={preview} alt="A csatolt kép" style={{ width: 72, height: 72, objectFit: "cover", borderRadius: 8 }} />
          <button type="button" className="btn" onClick={() => setImage(null)}>Kép eltávolítása</button>
        </div>
      ) : (
        <button type="button" className="btn block" style={{ margin: "8px 0" }}
                onClick={() => picker.current?.click()}>
          📷 Kép csatolása
        </button>
      )}
      {error && <p className="error">{error}</p>}
      <div className="row" style={{ gap: 8 }}>
        <button className="btn primary" style={{ flex: 1 }} disabled={busy || (!text.trim() && !image)}>
          {busy ? "Mentés…" : "Mentés"}
        </button>
        <button type="button" className="btn" style={{ flex: 1 }} disabled={busy} onClick={onCancel}>
          Mégse
        </button>
      </div>
    </form>
  );
}

function NoteList({ rows, onChange }: { rows: FixNote[]; onChange: () => void }) {
  const open = rows.filter((note) => !note.done);
  const done = rows.filter((note) => note.done);
  return (
    <>
      {open.map((note) => <NoteRow key={note.id} note={note} onChange={onChange} />)}
      {done.length > 0 && (
        <details style={{ marginTop: 14 }}>
          <summary className="muted" style={{ cursor: "pointer", fontSize: "0.86rem" }}>
            Kész ({done.length})
          </summary>
          {done.map((note) => <NoteRow key={note.id} note={note} onChange={onChange} />)}
        </details>
      )}
    </>
  );
}

function NoteRow({ note, onChange }: { note: FixNote; onChange: () => void }) {
  const [busy, setBusy] = useState(false);

  async function run(work: () => Promise<unknown>) {
    setBusy(true);
    try {
      await work();
      onChange();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="row" style={{
      gap: 10, alignItems: "flex-start",
      borderTop: "1px solid var(--grid)", paddingTop: 10, marginTop: 10,
      opacity: note.done ? 0.55 : 1,
    }}>
      <input
        type="checkbox"
        checked={note.done}
        disabled={busy}
        aria-label={note.done ? "Mégsem kész" : "Kész"}
        style={{ width: 24, height: 24, flex: "0 0 auto", marginTop: 2 }}
        onChange={() => run(() => api.updateFixNote(note.id, { done: !note.done }))}
      />
      {note.has_image && (
        <a href={api.fixNoteImageUrl(note.id)} target="_blank" rel="noreferrer" style={{ flex: "0 0 auto" }}>
          <img
            src={api.fixNoteImageUrl(note.id)}
            alt="Csatolt kép"
            loading="lazy"
            style={{ width: 56, height: 56, objectFit: "cover", borderRadius: 8, background: "var(--grid)" }}
          />
        </a>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ whiteSpace: "pre-wrap", textDecoration: note.done ? "line-through" : undefined }}>
          {note.text || <span className="muted">(csak kép)</span>}
        </div>
        <div className="muted" style={{ fontSize: "0.78rem" }}>
          {note.created_by ?? "?"} · {date(note.created_at)}
          {note.done_at && ` · kész: ${date(note.done_at)}`}
        </div>
      </div>
      <button
        className="btn"
        aria-label="Törlés"
        disabled={busy}
        // Its natural width: on a phone `.row > .btn` would stretch it over half the row
        // and squeeze the note into a narrow column.
        style={{ flex: "0 0 auto" }}
        onClick={() => {
          if (window.confirm("Törlöd ezt a jegyzetet?")) run(() => api.deleteFixNote(note.id));
        }}
      >
        🗑
      </button>
    </div>
  );
}
