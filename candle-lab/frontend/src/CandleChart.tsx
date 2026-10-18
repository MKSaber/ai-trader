import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

type Candle = {
  bar_start: string;
  open: number;
  high: number;
  low: number;
  close: number;
  closed: boolean;
};

type Pattern = {
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

type Setup = {
  entry_trigger: number;
  stop: number;
  target: number;
  status: string;
};

/**
 * Colorblind-safe palette (no red/green pair):
 * - Candles: blue = up, orange = down
 * - Signals: sky = BUY, magenta = SELL (shape + colour)
 */
const C = {
  ink: "#1d1d1f",
  grid: "rgba(0, 0, 0, 0.08)",
  bull: "#0071e3",
  bear: "#c45c00",
  forming: "#6e6e73",
  entry: "#0071e3",
  stop: "#c45c00",
  tp: "#5e5ce6",
  buyMark: "#0a84ff", // sky blue — BUY
  sellMark: "#bf5af2", // magenta — SELL
};

const MIN_VISIBLE = 8;
const PAD = { t: 28, r: 76, b: 28, l: 56 };
const CHART_H = 380;

export function CandleChart({
  candles,
  patterns,
  setups,
  focusIndex = 0,
}: {
  candles: Candle[];
  patterns: Pattern[];
  setups: Setup[];
  focusIndex?: number;
}) {
  const n = candles.length;
  const [visible, setVisible] = useState(n);
  const [start, setStart] = useState(0);
  const drag = useRef<{ x: number; start: number } | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef({ start: 0, visible: n });
  viewRef.current = { start, visible };

  useEffect(() => {
    setVisible(n);
    setStart(0);
  }, [n, candles[0]?.bar_start, candles[n - 1]?.bar_start]);

  const clampWindow = useCallback(
    (s: number, v: number) => {
      const vis = Math.min(Math.max(v, Math.min(MIN_VISIBLE, n)), n || 1);
      const st = Math.min(Math.max(0, s), Math.max(0, n - vis));
      return { start: st, visible: vis };
    },
    [n],
  );

  const applyView = useCallback(
    (s: number, v: number) => {
      const next = clampWindow(s, v);
      setStart(next.start);
      setVisible(next.visible);
    },
    [clampWindow],
  );

  const zoomBy = (factor: number, anchorFrac = 0.5) => {
    const { start: s0, visible: v0 } = viewRef.current;
    const nextVis = Math.round(v0 / factor);
    const anchor = s0 + v0 * anchorFrac;
    applyView(Math.round(anchor - nextVis * anchorFrac), nextVis);
  };

  const resetZoom = () => applyView(0, n);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (n < MIN_VISIBLE) return;
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const frac = Math.min(
        1,
        Math.max(0, (e.clientX - rect.left) / Math.max(rect.width, 1)),
      );
      const factor = e.deltaY < 0 ? 1.2 : 1 / 1.2;
      const { start: s0, visible: v0 } = viewRef.current;
      const nextVis = Math.round(v0 / factor);
      const anchor = s0 + v0 * frac;
      applyView(Math.round(anchor - nextVis * frac), nextVis);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [n, applyView]);

  const onPointerDown = (e: ReactPointerEvent) => {
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, start };
  };

  const onPointerMove = (e: ReactPointerEvent) => {
    if (!drag.current || visible >= n) return;
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    const dx = e.clientX - drag.current.x;
    const bars = Math.round((-dx / rect.width) * visible);
    const { start: s } = clampWindow(drag.current.start + bars, visible);
    setStart(s);
  };

  const onPointerUp = () => {
    drag.current = null;
  };

  const slice = useMemo(() => {
    const end = Math.min(n, start + visible);
    return candles.slice(start, end);
  }, [candles, start, visible, n]);

  const focus = patterns[focusIndex] ?? patterns[0] ?? null;

  if (!n) {
    return <p className="empty">No candles for this day yet.</p>;
  }

  if (!slice.length) {
    return (
      <div className="empty-block">
        <p className="empty">Zoom window is empty — reset the chart.</p>
        <button type="button" className="tool" onClick={resetZoom}>
          Reset
        </button>
      </div>
    );
  }

  const lows = slice.map((c) => c.low);
  const highs = slice.map((c) => c.high);
  const levelVals = [
    ...(focus
      ? [focus.entry_trigger, focus.stop, focus.take_profit].filter(
          (x): x is number => x != null,
        )
      : []),
    ...setups.flatMap((s) => [s.entry_trigger, s.stop, s.target]),
  ];
  const ymin = Math.min(...lows, ...(levelVals.length ? levelVals : lows));
  const ymax = Math.max(...highs, ...(levelVals.length ? levelVals : highs));
  const span = Math.max(ymax - ymin, 1e-6);

  const w = Math.max(640, slice.length * Math.max(8, 720 / Math.max(slice.length, 1)));
  const h = CHART_H;
  const count = Math.max(slice.length, 1);

  const x = (i: number) =>
    PAD.l + ((w - PAD.l - PAD.r) * (i + 0.5)) / count;
  const y = (price: number) =>
    PAD.t + ((h - PAD.t - PAD.b) * (ymax - price)) / span;
  const cw = Math.max(3, (w - PAD.l - PAD.r) / count - 2);

  const byTs = new Map(slice.map((c, i) => [c.bar_start.slice(0, 19), i]));
  const zoomed = visible < n;

  return (
    <div className="chart-panel">
      <div className="chart-toolbar">
        <span className="chart-hint">
          Scroll to zoom · drag to pan
          {zoomed ? ` · showing ${start + 1}–${start + slice.length} of ${n}` : ""}
        </span>
        <div className="chart-tools">
          <button type="button" className="tool" onClick={() => zoomBy(1.25)}>
            Zoom in
          </button>
          <button type="button" className="tool" onClick={() => zoomBy(1 / 1.25)}>
            Zoom out
          </button>
          <button
            type="button"
            className="tool"
            disabled={!zoomed}
            onClick={resetZoom}
          >
            Reset
          </button>
        </div>
      </div>

      <div
        className="chart-wrap"
        ref={wrapRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        style={{ cursor: zoomed ? "grab" : "default" }}
      >
        <svg width={w} height={h} role="img" aria-label="Candlestick chart">
          {[0, 0.25, 0.5, 0.75, 1].map((t) => {
            const py = PAD.t + (h - PAD.t - PAD.b) * t;
            const price = ymax - span * t;
            return (
              <g key={t}>
                <line
                  x1={PAD.l}
                  x2={w - PAD.r}
                  y1={py}
                  y2={py}
                  stroke={C.grid}
                />
                <text
                  x={6}
                  y={py + 4}
                  fill={C.ink}
                  fontSize="11"
                  fontWeight={600}
                  fontFamily="var(--font)"
                >
                  {price.toFixed(2)}
                </text>
              </g>
            );
          })}

          {slice.map((c, i) => {
            const bull = c.close >= c.open;
            const color = !c.closed ? C.forming : bull ? C.bull : C.bear;
            const xmid = x(i);
            return (
              <g key={c.bar_start}>
                <line
                  x1={xmid}
                  x2={xmid}
                  y1={y(c.high)}
                  y2={y(c.low)}
                  stroke={color}
                  strokeWidth={1.25}
                />
                <rect
                  x={xmid - cw / 2}
                  y={y(Math.max(c.open, c.close))}
                  width={cw}
                  height={Math.max(1, Math.abs(y(c.open) - y(c.close)))}
                  fill={color}
                  opacity={c.closed ? 1 : 0.45}
                />
              </g>
            );
          })}

          {patterns.map((p, idx) => {
            const key = p.confirm_bar_start.slice(0, 19);
            let i = byTs.get(key);
            if (i == null) {
              i = slice.findIndex((c) =>
                c.bar_start.startsWith(p.confirm_bar_start.slice(0, 16)),
              );
            }
            if (i < 0 || i == null) return null;
            const xmid = x(i);
            const active = idx === focusIndex;
            const isBuy = p.direction === "up";
            const color = isBuy ? C.buyMark : C.sellMark;
            const size = active ? 9 : 7;
            // BUY = triangle up above high; SELL = triangle down below low
            const tipY = isBuy
              ? y(p.pattern_high) - 14
              : y(p.pattern_low) + 14;
            const tri = isBuy
              ? `${xmid},${tipY - size} ${xmid - size},${tipY + size * 0.6} ${xmid + size},${tipY + size * 0.6}`
              : `${xmid},${tipY + size} ${xmid - size},${tipY - size * 0.6} ${xmid + size},${tipY - size * 0.6}`;
            const labelY = isBuy ? tipY - size - 4 : tipY + size + 12;
            return (
              <g key={`${p.pattern}-${idx}`} opacity={active ? 1 : 0.4}>
                <polygon
                  points={tri}
                  fill={color}
                  stroke="#fff"
                  strokeWidth={active ? 1.5 : 1}
                />
                <text
                  x={xmid + size + 4}
                  y={labelY}
                  fill={color}
                  fontSize="11"
                  fontWeight={700}
                  fontFamily="var(--font)"
                >
                  {isBuy ? "BUY" : "SELL"} · {p.pattern.replace(/_/g, " ")}
                </text>
              </g>
            );
          })}

          {focus?.entry_trigger != null && (
            <g>
              <line
                x1={PAD.l}
                x2={w - PAD.r}
                y1={y(focus.entry_trigger)}
                y2={y(focus.entry_trigger)}
                stroke={C.entry}
                strokeDasharray="5 4"
                strokeWidth={1.75}
              />
              <text
                x={w - PAD.r + 4}
                y={y(focus.entry_trigger) + 4}
                fill={C.entry}
                fontSize="11"
                fontWeight={700}
                fontFamily="var(--font)"
              >
                entry
              </text>
            </g>
          )}
          {focus?.stop != null && (
            <g>
              <line
                x1={PAD.l}
                x2={w - PAD.r}
                y1={y(focus.stop)}
                y2={y(focus.stop)}
                stroke={C.stop}
                strokeDasharray="5 4"
                strokeWidth={1.75}
              />
              <text
                x={w - PAD.r + 4}
                y={y(focus.stop) + 4}
                fill={C.stop}
                fontSize="11"
                fontWeight={700}
                fontFamily="var(--font)"
              >
                stop
              </text>
            </g>
          )}
          {focus?.take_profit != null && (
            <g>
              <line
                x1={PAD.l}
                x2={w - PAD.r}
                y1={y(focus.take_profit)}
                y2={y(focus.take_profit)}
                stroke={C.tp}
                strokeDasharray="3 4"
                strokeWidth={1.75}
              />
              <text
                x={w - PAD.r + 4}
                y={y(focus.take_profit) + 4}
                fill={C.tp}
                fontSize="11"
                fontWeight={700}
                fontFamily="var(--font)"
              >
                TP
              </text>
            </g>
          )}
        </svg>
      </div>

      <div className="legend">
        <span>
          <i style={{ background: C.bull }} /> Candle up
        </span>
        <span>
          <i style={{ background: C.bear }} /> Candle down
        </span>
        <span>
          <i
            style={{
              background: C.buyMark,
              clipPath: "polygon(50% 0, 0 100%, 100% 100%)",
              borderRadius: 0,
            }}
          />{" "}
          BUY signal
        </span>
        <span>
          <i
            style={{
              background: C.sellMark,
              clipPath: "polygon(0 0, 100% 0, 50% 100%)",
              borderRadius: 0,
            }}
          />{" "}
          SELL signal
        </span>
        <span>
          <i style={{ background: C.entry }} /> Entry
        </span>
        <span>
          <i style={{ background: C.stop }} /> Stop
        </span>
        <span>
          <i style={{ background: C.tp }} /> Take profit
        </span>
      </div>
    </div>
  );
}
