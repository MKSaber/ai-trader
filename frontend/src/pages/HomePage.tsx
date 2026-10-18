import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPost } from "../api/client";

type Health = {
  market_data_provider: string;
  demo_mode: boolean;
  disclaimer: string;
};

export function HomePage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState("");

  useEffect(() => {
    apiGet<Health>("/health").then(setHealth).catch(() => setHealth(null));
  }, []);

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    setToast("");
    try {
      const result = await fn();
      setToast(
        typeof result === "object"
          ? JSON.stringify(result, null, 2)
          : String(result),
      );
    } catch (e) {
      setToast(String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <section className="hero">
        <div className="eyebrow">London equity research</div>
        <h1>Clarity before conviction.</h1>
        <p>
          Import market data, learn interpretable patterns, and paper-trade
          setups — without promising an edge.
        </p>
        <div className="actions">
          <Link className="btn" to="/upload">
            Import data
          </Link>
          <button
            className="secondary"
            disabled={!!busy}
            onClick={() =>
              run("fixture", () =>
                apiPost("/provider/fetch?offline=true"),
              )
            }
          >
            {busy === "fixture" ? "Loading…" : "Try sample data"}
          </button>
        </div>
        {health && (
          <p style={{ marginTop: "1.25rem", fontSize: "0.85rem" }}>
            <span className="pill blue">{health.market_data_provider}</span>
            {health.demo_mode && (
              <span className="pill amber">demo mode</span>
            )}
          </p>
        )}
      </section>

      <div className="feature-row">
        {[
          {
            i: 0,
            icon: "↑",
            title: "Import with care",
            body: "OHLCV, trades, and commentary stay separate. Missing data disables predictions — never invents them.",
            to: "/upload",
          },
          {
            i: 1,
            icon: "ƒ",
            title: "See the formula",
            body: "Walk-forward models with readable coefficients. Promote a champion only when you choose to.",
            to: "/models",
          },
          {
            i: 2,
            icon: "◷",
            title: "Paper, not live",
            body: "Intraday setups with stops, targets, and costs. Replay history without touching a broker.",
            to: "/intraday",
          },
        ].map((f) => (
          <Link
            key={f.to}
            to={f.to}
            className="card"
            style={{ ["--i" as string]: f.i, color: "inherit" }}
          >
            <div className="feature-icon">{f.icon}</div>
            <h3>{f.title}</h3>
            <p>{f.body}</p>
          </Link>
        ))}
      </div>

      <div className="actions" style={{ marginTop: "2rem" }}>
        <button
          disabled={!!busy}
          onClick={() => run("train", () => apiPost("/research/train"))}
        >
          {busy === "train" ? "Training…" : "Train models"}
        </button>
        <button
          className="secondary"
          disabled={!!busy}
          onClick={() =>
            run("pipeline", () =>
              apiPost("/pipeline/run", { offline: true, dry_run: false }),
            )
          }
        >
          {busy === "pipeline" ? "Running…" : "Run offline pipeline"}
        </button>
      </div>

      {toast && (
        <div className="card" style={{ marginTop: "1.5rem" }}>
          <h3>Result</h3>
          <pre className="mono">{toast}</pre>
        </div>
      )}
    </div>
  );
}
