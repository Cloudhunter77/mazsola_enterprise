import { type FormEvent, useState } from "react";

import { api, ApiError, type SessionInfo } from "../lib/api";

export default function Login({ onSuccess }: { onSuccess: (session: SessionInfo) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSuccess(await api.login(username.trim(), password));
    } catch (err) {
      // One message for both halves, matching the server, which deliberately does not say
      // whether it was the name or the password.
      setError(
        err instanceof ApiError && err.status === 401
          ? "Hibás felhasználónév vagy jelszó."
          : (err as Error).message,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="content" style={{ maxWidth: 380, marginTop: "12vh" }}>
      <h1 style={{ marginBottom: 6 }}>🧾 Receipt Tracker</h1>
      <p className="muted" style={{ marginTop: 0, marginBottom: 22 }}>
        Blokkok rögzítése és költségkövetés.
      </p>
      <form className="card" onSubmit={submit}>
        <div className="field">
          <label htmlFor="username">Felhasználónév</label>
          <input
            id="username"
            autoFocus
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="password">Jelszó</label>
          <input
            id="password"
            type="password"
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
