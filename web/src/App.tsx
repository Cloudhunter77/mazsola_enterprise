import { useCallback, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";

import { api } from "./lib/api";
import { Loading } from "./components/ui";
import Capture from "./pages/Capture";
import Costs from "./pages/Costs";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import Manual from "./pages/Manual";
import Prices from "./pages/Prices";
import Receipts from "./pages/Receipts";
import RecurringPage from "./pages/Recurring";
import Review from "./pages/Review";
import TableView from "./pages/Table";

type Theme = "light" | "dark" | "system";

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

const TABS = [
  { to: "/", glyph: "📷", label: "Rögzítés", end: true },
  { to: "/blokkok", glyph: "🧾", label: "Blokkok", end: false },
  { to: "/tabla", glyph: "📋", label: "Tábla", end: false },
  { to: "/statisztika", glyph: "📊", label: "Statisztika", end: false },
  { to: "/arak", glyph: "🏷️", label: "Árak", end: false },
];

export default function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [theme, setTheme] = useTheme();
  const navigate = useNavigate();

  useEffect(() => {
    api.me()
      .then((info) => setAuthenticated(info.authenticated))
      .catch(() => setAuthenticated(false));
  }, []);

  const logout = useCallback(async () => {
    await api.logout().catch(() => undefined);
    setAuthenticated(false);
    navigate("/");
  }, [navigate]);

  if (authenticated === null) return <Loading label="Indulás…" />;
  if (!authenticated) return <Login onSuccess={() => setAuthenticated(true)} />;

  const nextTheme: Theme = theme === "dark" ? "light" : theme === "light" ? "system" : "dark";
  const themeGlyph = theme === "dark" ? "🌙" : theme === "light" ? "☀️" : "🌗";

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">🧾 Receipt Tracker</span>
        <span className="spacer" />
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
        <Routes>
          <Route path="/" element={<Capture />} />
          <Route path="/blokkok" element={<Receipts />} />
          <Route path="/blokkok/:id" element={<Review />} />
          <Route path="/tabla" element={<TableView />} />
          <Route path="/kezi" element={<Manual />} />
          <Route path="/elofizetesek" element={<RecurringPage />} />
          <Route path="/statisztika" element={<Dashboard />} />
          <Route path="/arak" element={<Prices />} />
          <Route path="/koltseg" element={<Costs />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <nav className="tabbar">
        {TABS.map((tab) => (
          <NavLink key={tab.to} to={tab.to} end={tab.end}>
            <span className="glyph" aria-hidden>{tab.glyph}</span>
            {tab.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
