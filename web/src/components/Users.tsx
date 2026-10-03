/** The household's logins, on the Rendszer page.
 *
 *  Everyone sees who is in the household and can change their own name and password.
 *  Adding someone, resetting a forgotten password and switching a login off are for
 *  admins - and the server refuses to let the last admin stop being one, so this screen
 *  does not have to guard against it as well.
 */

import { type FormEvent, useState } from "react";

import { api, type User } from "../lib/api";
import { useSession } from "../lib/session";
import { AsyncBlock, Card, useAsync } from "./ui";

export default function Users() {
  const session = useSession();
  const [reload, setReload] = useState(0);
  const users = useAsync(() => api.users(), [reload]);
  const refresh = () => setReload((n) => n + 1);
  const admin = session?.is_admin ?? false;

  return (
    <Card title="Felhasználók" note={session?.display_name ? `Bejelentkezve: ${session.display_name}` : undefined}>
      <AsyncBlock state={users}>
        {(rows) => (
          <>
            {rows.map((user) => (
              <UserRow key={user.id} user={user} admin={admin} onChange={refresh} />
            ))}
            {admin && <AddUser onAdded={refresh} />}
          </>
        )}
      </AsyncBlock>
    </Card>
  );
}

function UserRow({ user, admin, onChange }: { user: User; admin: boolean; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const canEdit = user.is_me || admin;

  return (
    <div style={{ borderTop: "1px solid var(--grid)", paddingTop: 10, marginTop: 10 }}>
      <div className="row" style={{ gap: 8, alignItems: "center" }}>
        <div style={{ flex: 1, minWidth: 0, opacity: user.active ? 1 : 0.5 }}>
          <strong>{user.display_name}</strong>
          {user.is_me && <span className="muted"> (te)</span>}
          <div className="muted" style={{ fontSize: "0.8rem" }}>
            {user.username}
            {user.is_admin && " · admin jog"}
            {!user.active && " · kikapcsolva"}
          </div>
        </div>
        {canEdit && (
          <button className="btn" onClick={() => setOpen(!open)}>
            {open ? "Bezár" : "Szerkesztés"}
          </button>
        )}
      </div>
      {open && <EditUser user={user} admin={admin} onDone={() => { setOpen(false); onChange(); }} />}
    </div>
  );
}

function EditUser({ user, admin, onDone }: { user: User; admin: boolean; onDone: () => void }) {
  const [name, setName] = useState(user.display_name);
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(body: Parameters<typeof api.updateUser>[1]) {
    setBusy(true);
    setError(null);
    try {
      await api.updateUser(user.id, body);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (password && password !== again) {
      setError("A két jelszó nem egyezik.");
      return;
    }
    const body: Parameters<typeof api.updateUser>[1] = {};
    if (name.trim() && name.trim() !== user.display_name) body.display_name = name.trim();
    if (password) {
      body.password = password;
      // Your own password needs the current one; an admin resetting someone else's does not.
      if (user.is_me) body.current_password = current;
    }
    if (Object.keys(body).length === 0) return onDone();
    save(body);
  }

  return (
    <form onSubmit={submit} style={{ marginTop: 10 }}>
      <div className="field">
        <label>Név, ahogy a többiek látják</label>
        <input value={name} onChange={(event) => setName(event.target.value)} maxLength={80} />
      </div>
      {user.is_me && (
        <div className="field">
          <label>Jelenlegi jelszó (csak jelszócseréhez)</label>
          <input type="password" autoComplete="current-password" value={current}
                 onChange={(event) => setCurrent(event.target.value)} />
        </div>
      )}
      <div className="field">
        <label>{user.is_me ? "Új jelszó" : "Új jelszó beállítása neki"}</label>
        <input type="password" autoComplete="new-password" value={password}
               onChange={(event) => setPassword(event.target.value)} />
      </div>
      {password && (
        <div className="field">
          <label>Új jelszó még egyszer</label>
          <input type="password" autoComplete="new-password" value={again}
                 onChange={(event) => setAgain(event.target.value)} />
        </div>
      )}
      {error && <p className="error">{error}</p>}
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <button className="btn primary" disabled={busy}>Mentés</button>
        {admin && !user.is_me && (
          <>
            <button type="button" className="btn" disabled={busy}
                    onClick={() => save({ is_admin: !user.is_admin })}>
              {user.is_admin ? "Admin jog elvétele" : "Legyen admin"}
            </button>
            <button type="button" className="btn danger" disabled={busy}
                    onClick={() => save({ active: !user.active })}>
              {user.active ? "Kikapcsolás" : "Visszakapcsolás"}
            </button>
          </>
        )}
      </div>
    </form>
  );
}

function AddUser({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createUser({
        username: username.trim(), display_name: name.trim(), password, is_admin: isAdmin,
      });
      setOpen(false);
      setName(""); setUsername(""); setPassword(""); setIsAdmin(false);
      onAdded();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button className="btn block" style={{ marginTop: 14 }} onClick={() => setOpen(true)}>
        + Új felhasználó
      </button>
    );
  }
  return (
    <form onSubmit={submit} style={{ borderTop: "1px solid var(--grid)", marginTop: 12, paddingTop: 12 }}>
      <div className="field">
        <label>Név</label>
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="pl. Petra" maxLength={80} />
      </div>
      <div className="field">
        <label>Felhasználónév (ezzel lép be)</label>
        <input value={username} autoCapitalize="none" spellCheck={false}
               onChange={(event) => setUsername(event.target.value)} placeholder="pl. petra" />
      </div>
      <div className="field">
        <label>Kezdő jelszó (legalább 8 karakter – utána ő maga megváltoztathatja)</label>
        <input type="password" autoComplete="new-password" value={password}
               onChange={(event) => setPassword(event.target.value)} />
      </div>
      <label style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12 }}>
        <input type="checkbox" checked={isAdmin} onChange={(event) => setIsAdmin(event.target.checked)}
               style={{ width: 22, height: 22 }} />
        Admin (ő is felvehet és kezelhet felhasználókat)
      </label>
      {error && <p className="error">{error}</p>}
      <div className="row" style={{ gap: 8 }}>
        <button className="btn primary" disabled={busy || !name.trim() || !username.trim() || password.length < 8}>
          Hozzáadás
        </button>
        <button type="button" className="btn" onClick={() => setOpen(false)}>Mégse</button>
      </div>
    </form>
  );
}
