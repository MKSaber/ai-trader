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
  available_days?: string[];
  suggested_day?: string | null;
  empty_reason?: string | null;
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

/** Last London weekday (Mon–Fri) as YYYY-MM-DD — weekends have no LSE bars. */
function lastLondonSessionDay(): string {
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/London",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const d = new Date();
  for (let i = 0; i < 10; i++) {
    const iso = fmt.format(d); // en-CA → YYYY-MM-DD
    const wd = new Date(`${iso}T12:00:00Z`).getUTCDay(); // 0 Sun … 6 Sat
    // Use London calendar weekday via noon UTC on that date as proxy
    const londonParts = new Intl.DateTimeFormat("en-US", {
      timeZone: "Europe/London",
      weekday: "short",
    }).formatToParts(d);
    const w = londonParts.find((p) => p.type === "weekday")?.value;
    if (w !== "Sat" && w !== "Sun") return iso;
    d.setUTCDate(d.getUTCDate() - 1);
  }
  return fmt.format(new Date());
}

export function App() {
  const [tab, setTab] = useState<"learn" | "live">("learn");
  const [health, setHealth] = useState<Health | null>(null);
  const [symbol, setSymbol] = useState(SYMBOLS[0]);
  const [day, setDay] = useState(lastLondonSessionDay);
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

  async function loadDay(forDay?: string) {
    // Guard: onClick={loadDay} would pass a SyntheticEvent — ignore non-strings.
    const requested = typeof forDay === "string" ? forDay : undefined;
    const d = requested ?? day;
    if (requested && requested !== day) setDay(requested);
    setBusy(true);
    setErr("");
    try {
      const data = await getJson<DayChart>(
        `/chart/day?symbol=${encodeURIComponent(symbol)}&day=${encodeURIComponent(String(d))}`,
      );
      setChart(data);
      setSelectedIdx(0);
      if (!data.candles?.length) {
        const suggest = data.suggested_day
          ? ` Latest available: ${data.suggested_day}.`
          : " Yahoo 5m only covers roughly the last ~60 days.";
        if (data.empty_reason === "weekend_no_lse_session") {
          setErr(`${d} is a weekend — LSE is closed.${suggest}`);
        } else {
          setErr(
            `No 5m candles for ${d}.${suggest} Pick a recent London weekday.`,
          );
        }
      }
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
      <header className="page-head">
        <div className="page-head-row">
          <div>
            <h1>Candle patterns</h1>
            <p>
              IG-style detections on delayed Yahoo 5m bars — paper longs for
              learning, not brokerage.
            </p>
          </div>
          <div className="segment" role="tablist">
            <button
              type="button"
              className={tab === "learn" ? "active" : ""}
              onClick={() => setTab("learn")}
            >
              Learn
            </button>
            <button
              type="button"
              className={tab === "live" ? "active" : ""}
              onClick={() => setTab("live")}
            >
              Live
            </button>
          </div>
        </div>
      </header>

      <div className="banner warn">
        <strong>Delayed feed</strong>
        <span>
          {health?.feed_label ?? "…"}
          {health?.feed_is_realtime ? " · real-time" : " · not real-time"}.{" "}
          {health?.disclaimer}
        </span>
      </div>

      {err && <div className="banner error">{err}</div>}

      {tab === "learn" && (
        <div className="stack">
          <div className="card controls">
            <div className="row">
              <label className="field">
                Stock
                <select
                  className="select"
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
              <label className="field">
                Day (London)
                <input
                  type="date"
                  value={day}
                  onChange={(e) => setDay(e.target.value)}
                />
              </label>
              <button
                type="button"
                disabled={busy}
                onClick={() => void loadDay()}
              >
                {busy ? "Loading…" : "Load day"}
              </button>
            </div>
            {chart && (
              <p className="meta">
                {chart.candles.length} candles · {chart.patterns.length}{" "}
                patterns · delay ≈{" "}
                {chart.feed.delay_seconds?.toFixed?.(0) ?? "—"}s
              </p>
            )}
          </div>

          <div className="card chart-card">
            <div className="card-title-row">
              <h3>
                {symbol} · {day}
              </h3>
              <span className="meta-inline">
                ▲ sky = BUY · ▼ magenta = SELL · candles blue/orange
              </span>
            </div>
            {chart && chart.candles.length > 0 ? (
              <CandleChart
                candles={chart.candles}
                patterns={chart.patterns}
                setups={chart.setups}
                focusIndex={selectedIdx}
              />
            ) : (
              <div className="empty-block">
                <p className="empty">
                  {busy
                    ? "Loading candles…"
                    : chart
                      ? `No candles for ${chart.day}. Weekends and holidays have no LSE session.`
                      : "Load a London session weekday to see candles."}
                </p>
                {chart?.suggested_day && (
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() => loadDay(chart.suggested_day!)}
                  >
                    Load latest session ({chart.suggested_day})
                  </button>
                )}
                {!!chart?.available_days?.length && (
                  <p className="meta" style={{ marginTop: "0.75rem" }}>
                    Available: {chart.available_days.slice(0, 8).join(", ")}
                  </p>
                )}
              </div>
            )}
          </div>

          <div className="card">
            <div className="card-title-row">
              <h3>Detected patterns</h3>
              <span className="meta-inline">
                Click a row to focus entry / stop / TP
              </span>
            </div>
            {!chart?.patterns?.length ? (
              <p className="empty">
                No patterns on this day. Try a recent LSE session day.
              </p>
            ) : (
              <div className="table-wrap">
                <table>
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
                        className={i === selectedIdx ? "selected" : undefined}
                        onClick={() => setSelectedIdx(i)}
                      >
                        <td className="mono">
                          {p.confirm_bar_start.replace("T", " ").slice(0, 19)}
                        </td>
                        <td>
                          <span
                            className={`pill ${
                              p.direction === "up" ? "blue" : "orange"
                            }`}
                          >
                            {p.pattern}
                          </span>
                        </td>
                        <td className="cell-strong">{p.action}</td>
                        <td className="cell-strong">
                          {p.entry_trigger != null
                            ? p.entry_trigger.toFixed(4)
                            : "—"}
                        </td>
                        <td className="cell-strong">
                          {p.stop != null ? p.stop.toFixed(4) : "—"}
                        </td>
                        <td className="cell-strong">
                          {p.take_profit != null
                            ? p.take_profit.toFixed(4)
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {selectedPattern && (
              <details className="details">
                <summary>Detector conditions</summary>
                <pre className="mono">
                  {JSON.stringify(selectedPattern.conditions, null, 2)}
                </pre>
              </details>
            )}
          </div>
        </div>
      )}

      {tab === "live" && (
        <div className="card">
          <h3>Live session</h3>
          <p className="hint">
            Start a session, then poll during the LSE day. Same delayed Yahoo
            feed — paper only.
          </p>
          <div className="row">
            <button
              type="button"
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
              type="button"
              className="secondary"
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
            <p className="meta" style={{ marginTop: "1rem" }}>
              Session run id: <strong className="cell-strong">{runId}</strong>
            </p>
          )}
          {session && (
            <pre className="mono">{JSON.stringify(session, null, 2)}</pre>
          )}
        </div>
      )}

      <p className="footer-note">
        Research only · Delayed feed · Paper setups · No live orders
      </p>
    </div>
  );
}
