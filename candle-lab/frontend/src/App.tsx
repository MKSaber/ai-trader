import { useEffect, useMemo, useState } from "react";
import { CandleChart } from "./CandleChart";

const API = import.meta.env.VITE_CANDLE_API || "/api";
const SYMBOLS = ["VOD.L", "BP.L", "HSBA.L", "GSK.L", "AZN.L"];

type Health = {
  feed_label: string;
  feed_is_realtime: boolean;
  disclaimer: string;
  symbols: string[];
};

type DayChart = {
  symbol: string;
  day: string;
  feed: {
    message: string;
    delay_seconds: number | null;
    healthy: boolean;
  };
  candles: Array<{
    bar_start: string;
    open: number;
    high: number;
    low: number;
    close: number;
    closed: boolean;
  }>;
  patterns: Array<{
    pattern: string;
    direction: string;
    confirm_bar_start: string;
    entry_trigger: number | null;
    stop: number | null;
    take_profit: number | null;
    action: string;
    pattern_high: number;
    pattern_low: number;
    conditions: Record<string, unknown>;
  }>;
  setups: Array<{
    id: number;
    pattern: string;
    status: string;
    entry_trigger: number;
    stop: number;
    target: number;
  }>;
  note: string;
};

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function postJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

export function App() {
  const [tab, setTab] = useState<"learn" | "live">("learn");
  const [health, setHealth] = useState<Health | null>(null);
  const [symbol, setSymbol] = useState(SYMBOLS[0]);
  const [day, setDay] = useState(todayISO());
  const [chart, setChart] = useState<DayChart | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [runId, setRunId] = useState<number | null>(null);
  const [session, setSession] = useState<Record<string, unknown> | null>(null);
  const [selectedIdx, setSelectedIdx] = useState(0);

  useEffect(() => {
    getJson<Health>("/health")
      .then(setHealth)
      .catch((e) => setErr(String(e)));
  }, []);

  async function loadDay() {
    setBusy(true);
    setErr("");
    try {
      const data = await getJson<DayChart>(
        `/chart/day?symbol=${encodeURIComponent(symbol)}&day=${day}`,
      );
      setChart(data);
      setSelectedIdx(0);
    } catch (e) {
      setErr(String(e));
      setChart(null);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (tab === "learn") loadDay();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const selectedPattern = useMemo(
    () => chart?.patterns?.[selectedIdx] ?? chart?.patterns?.[0] ?? null,
    [chart, selectedIdx],
  );

  return (
    <div className="app">
      <header>
        <h1>Live Candle Pattern Test</h1>
        <p>
          Independent of LSE Pattern Lab. Detects IG-defined candlestick
          formations on delayed Yahoo 5m bars and papers long setups for
          learning — not live brokerage.
        </p>
      </header>

      <div className="banner">
        FEED: {health?.feed_label ?? "…"} —{" "}
        {health?.feed_is_realtime
          ? "REAL-TIME"
          : "DELAYED (not suitable to prove timely live execution)"}
        . {health?.disclaimer}
      </div>

      <div className="tabs">
        <button
          className={tab === "learn" ? "active" : ""}
          onClick={() => setTab("learn")}
        >
          Learn · stock day
        </button>
        <button
          className={tab === "live" ? "active" : ""}
          onClick={() => setTab("live")}
        >
          Live session
        </button>
      </div>

      {err && (
        <div className="banner" style={{ color: "#f07178" }}>
          {err}
        </div>
      )}

      {tab === "learn" && (
        <>
          <div className="panel">
            <div className="row">
              <label>
                Stock
                <select
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                >
                  {SYMBOLS.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Day (London)
                <input
                  type="date"
                  value={day}
                  onChange={(e) => setDay(e.target.value)}
                />
              </label>
              <button className="primary" disabled={busy} onClick={loadDay}>
                {busy ? "Loading…" : "Show candles & patterns"}
              </button>
            </div>
            {chart && (
              <p style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
                {chart.note} Delay ≈ {chart.feed.delay_seconds?.toFixed?.(0) ?? "—"}s.
              </p>
            )}
          </div>

          <div className="panel">
            <h3 style={{ marginTop: 0 }}>
              {symbol} · {day}
            </h3>
            {chart && (
              <CandleChart
                candles={chart.candles}
                patterns={chart.patterns}
                setups={chart.setups}
                focusIndex={selectedIdx}
              />
            )}
          </div>

          <div className="panel">
            <h3 style={{ marginTop: 0 }}>Detected patterns</h3>
            <p style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
              Click a row to focus entry / stop / take-profit overlays on the
              chart. Bullish patterns show a buy setup; bearish are observation /
              exit cues (long-only paper).
            </p>
            {!chart?.patterns?.length ? (
              <p style={{ color: "var(--muted)" }}>
                No patterns on this day (or still loading). Try a recent LSE
                session day.
              </p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Pattern</th>
                    <th>Action</th>
                    <th>Entry</th>
                    <th>Stop</th>
                    <th>Take profit</th>
                  </tr>
                </thead>
                <tbody>
                  {chart.patterns.map((p, i) => (
                    <tr
                      key={`${p.confirm_bar_start}-${i}`}
                      onClick={() => setSelectedIdx(i)}
                      style={{
                        cursor: "pointer",
                        outline:
                          i === selectedIdx
                            ? "1px solid var(--accent)"
                            : undefined,
                      }}
                    >
                      <td className="mono">
                        {p.confirm_bar_start.replace("T", " ").slice(0, 19)}
                      </td>
                      <td>
                        <span
                          className={`pill ${p.direction === "up" ? "up" : "down"}`}
                        >
                          {p.pattern}
                        </span>
                      </td>
                      <td>{p.action}</td>
                      <td>
                        {p.entry_trigger != null
                          ? p.entry_trigger.toFixed(4)
                          : "—"}
                      </td>
                      <td>{p.stop != null ? p.stop.toFixed(4) : "—"}</td>
                      <td>
                        {p.take_profit != null
                          ? p.take_profit.toFixed(4)
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {selectedPattern && (
              <pre className="mono" style={{ marginTop: "0.75rem" }}>
                {JSON.stringify(selectedPattern.conditions, null, 2)}
              </pre>
            )}
          </div>
        </>
      )}

      {tab === "live" && (
        <div className="panel">
          <p style={{ color: "var(--muted)" }}>
            Start a session runner, then poll during the LSE day. Uses the same
            delayed Yahoo feed — labelled delayed, paper only.
          </p>
          <div className="row">
            <button
              className="primary"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setErr("");
                try {
                  const r = await postJson<{ session_run_id: number }>(
                    "/session/start",
                  );
                  setRunId(r.session_run_id);
                  setSession(r);
                } catch (e) {
                  setErr(String(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Start session
            </button>
            <button
              className="primary"
              disabled={busy || runId == null}
              onClick={async () => {
                if (runId == null) return;
                setBusy(true);
                try {
                  await postJson(`/session/${runId}/poll`);
                  const s = await getJson(`/session/${runId}`);
                  setSession(s);
                } catch (e) {
                  setErr(String(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Poll feed now
            </button>
          </div>
          {runId != null && (
            <p>
              Session run id: <strong>{runId}</strong>
            </p>
          )}
          {session && (
            <pre className="mono">{JSON.stringify(session, null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  );
}
