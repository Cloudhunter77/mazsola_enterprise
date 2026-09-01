import { type FormEvent, useState } from "react";

import { api } from "../lib/api";

export default function Login({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(password);
      onSuccess();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="content" style={{ maxWidth: 380, marginTop: "12vh" }}>
      <h1 style={{ marginBottom: 6 }}>🍇 Mazsola</h1>
      <p className="muted" style={{ marginTop: 0, marginBottom: 22 }}>
        Blokkok rögzítése és költségkövetés.
      </p>
      <form className="card" onSubmit={submit}>
        <div className="field">
          <label htmlFor="password">Jelszó</label>
          <input
            id="password"
            type="password"
            autoFocus
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        {error && <p className="error">{error}</p>}
        <button className="btn primary big" style={{ width: "100%" }} disabled={busy || !password}>
          {busy ? "Belépés…" : "Belépés"}
        </button>
      </form>
    </div>
  );
}
