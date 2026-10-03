import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { api, type SessionInfo } from "./lib/api";
import { SessionContext } from "./lib/session";
import { SECTIONS, sectionFor } from "./lib/nav";
import { Loading } from "./components/ui";
import Capture from "./pages/Capture";
import Categorise from "./pages/Categorise";
import Costs from "./pages/Costs";
import Dashboard from "./pages/Dashboard";
import Labels from "./pages/Labels";
import Settle from "./pages/Settle";
import ShelfPrices from "./pages/ShelfPrices";
import Shopping from "./pages/Shopping";
import Login from "./pages/Login";
import Manual from "./pages/Manual";
import Prices from "./pages/Prices";
import Receipts from "./pages/Receipts";
import RecurringPage from "./pages/Recurring";
import Review from "./pages/Review";
import System from "./pages/System";
import TableView from "./pages/Table";

type Theme = "light" | "dark" | "system";

const ANONYMOUS: SessionInfo = {
  authenticated: false, subject: null, user_id: null, display_name: null, is_admin: false,
};

function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem("receipt-tracker-theme") as Theme) ?? "system";
    } catch {
      return "system"; // private windows and blocked site data both throw here
    }
  });

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("receipt-tracker-theme", theme);
    } catch {
      /* remembering the choice is a convenience, not a requirement */
    }
  }, [theme]);

  return [theme, setTheme];
}

export default function App() {
  // null while asking; then who is logged in, or `authenticated: false`.
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [theme, setTheme] = useTheme();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    api.me()
      .then(setSession)
      .catch(() => setSession(ANONYMOUS));
  }, []);

  const logout = useCallback(async () => {
    await api.logout().catch(() => undefined);
    setSession(ANONYMOUS);
    navigate("/");
  }, [navigate]);

  if (session === null) return <Loading label="Indulás…" />;
  if (!session.authenticated) return <Login onSuccess={setSession} />;

  const nextTheme: Theme = theme === "dark" ? "light" : theme === "light" ? "system" : "dark";
  const themeGlyph = theme === "dark" ? "🌙" : theme === "light" ? "☀️" : "🌗";
  const section = sectionFor(location.pathname);

  return (
    <SessionContext.Provider value={session}>
    <div className="app">
      <header className="topbar">
        <span className="brand">🧾 Receipt Tracker</span>
        <span className="spacer" />
        {/* Version, database and worker state: looked at rarely, so it is not a tab. */}
        <Link
          className="btn"
          to="/rendszer"
          title="Rendszer: verzió és állapot"
          aria-label="Rendszer"
          aria-current={location.pathname === "/rendszer" ? "page" : undefined}
        >
          ⚙
        </Link>
        <button
          className="btn"
          onClick={() => setTheme(nextTheme)}
          title={`Téma: ${theme}. Váltás: ${nextTheme}`}
          aria-label={`Téma váltása (jelenleg: ${theme})`}
        >
          {themeGlyph}
        </button>
        <button className="btn" onClick={logout}>Kilépés</button>
      </header>

      <main className="content">
        {section && section.pages.length > 1 && (
          <nav className="subnav" aria-label={section.label}>
            {section.pages.map((page) => (
              <NavLink key={page.to} to={page.to} end>
                {page.label}
              </NavLink>
            ))}
          </nav>
        )}
        <Routes>
          <Route path="/" element={<Capture />} />
          <Route path="/blokkok" element={<Receipts />} />
          <Route path="/blokkok/:id" element={<Review />} />
          <Route path="/tabla" element={<TableView />} />
          <Route path="/kezi" element={<Manual />} />
          <Route path="/rendszer" element={<System />} />
          <Route path="/elofizetesek" element={<RecurringPage />} />
          <Route path="/elszamolas" element={<Settle />} />
          <Route path="/statisztika" element={<Dashboard />} />
          <Route path="/arak" element={<Prices />} />
          <Route path="/arcimkek" element={<Labels />} />
          <Route path="/polcarak" element={<ShelfPrices />} />
          <Route path="/lista" element={<Shopping />} />
          <Route path="/kategorizalas" element={<Categorise />} />
          <Route path="/koltseg" element={<Costs />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <nav className="tabbar">
        {/* Active by section rather than by URL prefix: the Rögzítés tab owns "/", which
            is a prefix of everything, and the Blokkok tab owns /tabla, which is not a
            prefix of anything it shares with /blokkok. */}
        {SECTIONS.map((tab) => (
          <Link
            key={tab.label}
            to={tab.pages[0].to}
            className={tab === section ? "active" : undefined}
            aria-current={tab === section ? "page" : undefined}
          >
            <span className="glyph" aria-hidden>{tab.glyph}</span>
            {tab.label}
          </Link>
        ))}
      </nav>
    </div>
    </SessionContext.Provider>
  );
}
