import { NavLink, Route, Routes } from "react-router-dom";
import { UploadPage } from "./pages/UploadPage";
import { CoveragePage } from "./pages/CoveragePage";
import { ForecastsPage } from "./pages/ForecastsPage";
import { ModelsPage } from "./pages/ModelsPage";
import { IntradayLabPage } from "./pages/IntradayLabPage";
import { PipelinePage } from "./pages/PipelinePage";
import { FindingsPage } from "./pages/FindingsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { StocksPage } from "./pages/StocksPage";
import { HomePage } from "./pages/HomePage";
import { PatternsPage } from "./pages/PatternsPage";
import { BacktestsPage } from "./pages/BacktestsPage";
import { DriftPage } from "./pages/DriftPage";
import { CandleLabPage } from "./pages/CandleLabPage";

const links = [
  ["/", "Overview"],
  ["/upload", "Data"],
  ["/coverage", "Coverage"],
  ["/stocks", "Stocks"],
  ["/forecasts", "Forecasts"],
  ["/patterns", "Patterns"],
  ["/candle-lab", "Candle patterns"],
  ["/models", "Models"],
  ["/backtests", "Backtests"],
  ["/intraday", "Intraday"],
  ["/findings", "Findings"],
  ["/drift", "Drift"],
  ["/pipeline", "Pipeline"],
  ["/settings", "Settings"],
] as const;

export function App() {
  return (
    <div className="app-shell">
      <header className="topnav">
        <NavLink to="/" className="topnav-brand" end>
          <span className="topnav-mark">L</span>
          Pattern Lab
        </NavLink>
        <nav className="topnav-links" aria-label="Primary">
          {links.map(([to, label]) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) => (isActive ? "active" : undefined)}
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </header>

      <div className="main">
        <nav className="mobile-nav" aria-label="Mobile">
          {links.map(([to, label]) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) => (isActive ? "active" : undefined)}
            >
              {label}
            </NavLink>
          ))}
        </nav>

        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/coverage" element={<CoveragePage />} />
          <Route path="/stocks" element={<StocksPage />} />
          <Route path="/forecasts" element={<ForecastsPage />} />
          <Route path="/patterns" element={<PatternsPage />} />
          <Route path="/candle-lab" element={<CandleLabPage />} />
          <Route path="/models" element={<ModelsPage />} />
          <Route path="/backtests" element={<BacktestsPage />} />
          <Route path="/intraday" element={<IntradayLabPage />} />
          <Route path="/findings" element={<FindingsPage />} />
          <Route path="/drift" element={<DriftPage />} />
          <Route path="/pipeline" element={<PipelinePage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>

        <p className="footer-note">
          Research only · No live orders · No promised profits
        </p>
      </div>
    </div>
  );
}
