/** Small shared UI pieces and the data-loading hook every page uses. */

import { type DependencyList, type ReactNode, useCallback, useEffect, useState } from "react";

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/** Load something once, expose loading and error, and allow an explicit reload. */
export function useAsync<T>(loader: () => Promise<T>, deps: DependencyList = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    loader()
      .then((result) => { if (!cancelled) { setData(result); setError(null); } })
      .catch((err: Error) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, loading, error, reload };
}

export function Card({ title, note, action, children }: {
  title?: string; note?: string; action?: ReactNode; children: ReactNode;
}) {
  return (
    <section className="card">
      {(title || action) && (
        <header className="card-header">
          {title && <h2>{title}</h2>}
          {note && <span className="card-note">{note}</span>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Tile({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function Loading({ label = "Betöltés…" }: { label?: string }) {
  return (
    <p className="empty">
      <span className="spinner" aria-hidden /> <span style={{ marginLeft: 8 }}>{label}</span>
    </p>
  );
}

/** Renders the usual loading / error / empty states so pages do not each re-invent them. */
export function AsyncBlock<T>({ state, empty, children }: {
  state: AsyncState<T>;
  empty?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  if (state.loading && state.data === null) return <Loading />;
  if (state.error) return <p className="empty error">{state.error}</p>;
  if (state.data === null) return <Empty>{empty ?? "Nincs adat."}</Empty>;
  const isEmptyArray = Array.isArray(state.data) && state.data.length === 0;
  if (isEmptyArray && empty) return <Empty>{empty}</Empty>;
  return <>{children(state.data)}</>;
}
