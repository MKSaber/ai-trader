import { useEffect, useMemo, useRef, useState } from "react";
import { CandleChart } from "./CandleChart";

export type ReplayCandle = {
  bar_start: string;
  open: number;
  high: number;
  low: number;
  close: number;
  closed: boolean;
};

export type ReplayPattern = {
  pattern: string;
  direction: string;
  confirm_bar_start: string;
  entry_trigger: number | null;
  stop: number | null;
  take_profit: number | null;
  action: string;
  pattern_high: number;
  pattern_low: number;
};

type EventRow = {
  id: string;
  bar: number;
  time: string;
  kind: "buy" | "sell";
  pattern: string;
  entry: number | null;
  stop: number | null;
  tp: number | null;
};

const SPEEDS = [1, 2, 5, 10, 60] as const;
/** Wall-clock ms per 5m bar at 1× (compressed day: 1s/bar). Realtime would be 300_000. */
const BASE_MS_PER_BAR = 1000;

function barKey(ts: string) {
  return ts.slice(0, 19);
}

export function DayReplay({
  symbol,
  day,
  candles,
  patterns,
}: {
  symbol: string;
  day: string;
  candles: ReplayCandle[];
  patterns: ReplayPattern[];
}) {
  const n = candles.length;
  const [cursor, setCursor] = useState(0); // how many bars revealed (0..n)
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(10);
  const [focusIdx, setFocusIdx] = useState(0);
  const [flash, setFlash] = useState<string | null>(null);
  const seenRef = useRef<Set<string>>(new Set());

  // Reset when day/symbol/candles change
  useEffect(() => {
    setCursor(0);
    setPlaying(false);
    setFocusIdx(0);
    setFlash(null);
    seenRef.current = new Set();
  }, [symbol, day, candles]);

  const visibleCandles = useMemo(() => {
    if (cursor <= 0) return [];
    return candles.slice(0, cursor).map((c, i, arr) => ({
      ...c,
      // Last revealed bar plays as "forming" until we step past it (except when finished)
      closed: i < arr.length - 1 || cursor >= n ? c.closed : false,
    }));
  }, [candles, cursor, n]);

  const lastRevealedKey =
    cursor > 0 ? barKey(candles[cursor - 1].bar_start) : "";

  /** Patterns whose confirm bar has already closed in the replay (no future peek). */
  const revealedPatterns = useMemo(() => {
    if (cursor <= 0) return [];
    const keys = new Set(
      candles.slice(0, cursor).map((c) => barKey(c.bar_start)),
    );
    return patterns.filter((p) => keys.has(barKey(p.confirm_bar_start)));
  }, [candles, cursor, patterns]);

  // Flash + log when a new pattern appears at this cursor
  useEffect(() => {
    if (cursor <= 0) return;
    const keys = new Set(
      candles.slice(0, cursor).map((c) => barKey(c.bar_start)),
    );
    const fresh = patterns.filter((p) => {
      const k = `${p.pattern}|${barKey(p.confirm_bar_start)}`;
      if (!keys.has(barKey(p.confirm_bar_start))) return false;
      if (seenRef.current.has(k)) return false;
      seenRef.current.add(k);
      return true;
    });
    if (fresh.length) {
      const last = fresh[fresh.length - 1];
      setFocusIdx(revealedPatterns.findIndex(
        (p) =>
          p.pattern === last.pattern &&
          barKey(p.confirm_bar_start) === barKey(last.confirm_bar_start),
      ));
      setFlash(
        `${last.direction === "up" ? "BUY" : "SELL"} ${last.pattern.replace(/_/g, " ")} · entry ${last.entry_trigger?.toFixed(2) ?? "—"} · stop ${last.stop?.toFixed(2) ?? "—"} · TP ${last.take_profit?.toFixed(2) ?? "—"}`,
      );
    }
  }, [cursor, candles, patterns, revealedPatterns]);

  const events: EventRow[] = useMemo(() => {
    return revealedPatterns.map((p, i) => {
      const bi = candles.findIndex(
        (c) => barKey(c.bar_start) === barKey(p.confirm_bar_start),
      );
      return {
        id: `${p.pattern}-${p.confirm_bar_start}-${i}`,
        bar: bi + 1,
        time: p.confirm_bar_start.replace("T", " ").slice(0, 19),
        kind: p.direction === "up" ? "buy" : "sell",
        pattern: p.pattern,
        entry: p.entry_trigger,
        stop: p.stop,
        tp: p.take_profit,
      };
    });
  }, [revealedPatterns, candles]);

  // Playback timer
  useEffect(() => {
    if (!playing || cursor >= n) {
      if (cursor >= n) setPlaying(false);
      return;
    }
    const ms = Math.max(16, BASE_MS_PER_BAR / speed);
    const id = window.setTimeout(() => {
      setCursor((c) => Math.min(n, c + 1));
    }, ms);
    return () => window.clearTimeout(id);
  }, [playing, cursor, n, speed]);

  const progress = n ? cursor / n : 0;
  const clock =
    cursor > 0
      ? candles[cursor - 1].bar_start.replace("T", " ").slice(0, 19)
      : "— not started —";

  return (
    <div className="stack">
      <div className="card controls">
        <div className="card-title-row">
          <h3>
            Day simulator · {symbol} · {day}
          </h3>
          <span className="meta-inline">
            TP/SL set when the pattern candle closes — not after the full day
          </span>
        </div>
        <p className="hint">
          Bars arrive one-by-one as if live. Detection runs only on candles
          revealed so far (same rules as paper engine). Speeds are relative to
          1s per 5m bar (×60 ≈ 1 session minute per wall second).
        </p>

        <div className="row" style={{ alignItems: "center" }}>
          <button
            type="button"
            disabled={n === 0}
            onClick={() => {
              if (cursor >= n) {
                setCursor(0);
                seenRef.current = new Set();
                setFlash(null);
              }
              setPlaying((p) => !p);
            }}
          >
            {playing ? "Pause" : cursor >= n ? "Replay" : "Play"}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={playing || cursor >= n}
            onClick={() => setCursor((c) => Math.min(n, c + 1))}
          >
            Step +1
          </button>
          <button
            type="button"
            className="secondary"
            disabled={playing}
            onClick={() => {
              setPlaying(false);
              setCursor(0);
              seenRef.current = new Set();
              setFlash(null);
              setFocusIdx(0);
            }}
          >
            Reset
          </button>

          <label className="field" style={{ minWidth: "auto" }}>
            Speed
            <div className="segment speed-seg" role="group">
              {SPEEDS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={speed === s ? "active" : ""}
                  onClick={() => setSpeed(s)}
                >
                  ×{s}
                </button>
              ))}
            </div>
          </label>
        </div>

        <div className="replay-progress">
          <div className="replay-bar" style={{ width: `${progress * 100}%` }} />
        </div>
        <p className="meta">
          Bar {cursor}/{n} · clock {clock}
          {lastRevealedKey ? ` · last ${lastRevealedKey.replace("T", " ")}` : ""}
        </p>

        {flash && (
          <div className={`banner ${flash.startsWith("BUY") ? "info" : "warn"}`}>
            <strong>Just detected</strong>
            <span>{flash}</span>
          </div>
        )}
      </div>

      <div className="card chart-card">
        <div className="card-title-row">
          <h3>Live-as-of replay</h3>
          <span className="meta-inline">
            {revealedPatterns.length} signal
            {revealedPatterns.length === 1 ? "" : "s"} so far
          </span>
        </div>
        {cursor === 0 ? (
          <p className="empty">Press Play to start the session simulation.</p>
        ) : (
          <CandleChart
            candles={visibleCandles}
            patterns={revealedPatterns}
            setups={[]}
            focusIndex={Math.max(0, focusIdx)}
          />
        )}
      </div>

      <div className="card">
        <div className="card-title-row">
          <h3>Detection log (on the go)</h3>
          <span className="meta-inline">
            Levels frozen at confirm bar — no look-ahead
          </span>
        </div>
        {!events.length ? (
          <p className="empty">No patterns yet in the revealed bars.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Bar #</th>
                  <th>Time</th>
                  <th>Side</th>
                  <th>Pattern</th>
                  <th>Entry</th>
                  <th>Stop</th>
                  <th>Take profit</th>
                </tr>
              </thead>
              <tbody>
                {[...events].reverse().map((e, i) => (
                  <tr
                    key={e.id}
                    className={i === 0 ? "selected" : undefined}
                    onClick={() => {
                      const idx = revealedPatterns.findIndex(
                        (p) =>
                          `${p.pattern}-${p.confirm_bar_start}` ===
                          `${e.pattern}-${e.time.replace(" ", "T")}`,
                      );
                      // fallback match by pattern + time prefix
                      const j = revealedPatterns.findIndex(
                        (p) =>
                          p.pattern === e.pattern &&
                          barKey(p.confirm_bar_start) ===
                            barKey(e.time.replace(" ", "T")),
                      );
                      setFocusIdx(j >= 0 ? j : idx >= 0 ? idx : 0);
                    }}
                  >
                    <td className="cell-strong">{e.bar}</td>
                    <td className="mono">{e.time}</td>
                    <td>
                      <span
                        className={`pill ${e.kind === "buy" ? "blue" : "orange"}`}
                      >
                        {e.kind.toUpperCase()}
                      </span>
                    </td>
                    <td className="cell-strong">{e.pattern}</td>
                    <td className="cell-strong">
                      {e.entry != null ? e.entry.toFixed(4) : "—"}
                    </td>
                    <td className="cell-strong">
                      {e.stop != null ? e.stop.toFixed(4) : "—"}
                    </td>
                    <td className="cell-strong">
                      {e.tp != null ? e.tp.toFixed(4) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
