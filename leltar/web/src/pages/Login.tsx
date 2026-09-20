import { type FormEvent, useState } from "react";

import { api } from "../lib/api";
import { Card } from "../components/ui";

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
      <Card title="📦 Leltár">
        <form onSubmit={submit}>
          <label className="field">
            Jelszó
            <input
              type="password"
              value={password}
              autoFocus
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button className="btn primary block" disabled={busy || !password}>
            {busy ? "Belépés…" : "Belépés"}
          </button>
        </form>
      </Card>
    </div>
  );
}
