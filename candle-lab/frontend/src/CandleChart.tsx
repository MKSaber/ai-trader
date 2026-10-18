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
  if (!candles.length) {
    return <p style={{ color: "var(--muted)" }}>No candles for this day yet.</p>;
  }

  const w = Math.max(720, candles.length * 12);
  const h = 360;
  const pad = { t: 24, r: 72, b: 28, l: 56 };
  const focus = patterns[focusIndex] ?? patterns[0] ?? null;
  const lows = candles.map((c) => c.low);
  const highs = candles.map((c) => c.high);
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

  const x = (i: number) =>
    pad.l + ((w - pad.l - pad.r) * (i + 0.5)) / candles.length;
  const y = (price: number) =>
    pad.t + ((h - pad.t - pad.b) * (ymax - price)) / span;
  const cw = Math.max(3, (w - pad.l - pad.r) / candles.length - 2);

  const byTs = new Map(candles.map((c, i) => [c.bar_start.slice(0, 19), i]));

  return (
    <div className="chart-wrap">
      <svg width={w} height={h} role="img" aria-label="Candlestick chart">
        {/* grid */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const py = pad.t + (h - pad.t - pad.b) * t;
          const price = ymax - span * t;
          return (
            <g key={t}>
              <line
                x1={pad.l}
                x2={w - pad.r}
                y1={py}
                y2={py}
                stroke="rgba(255,255,255,0.06)"
              />
              <text
                x={4}
                y={py + 4}
                fill="#8b9aab"
                fontSize="10"
              >
                {price.toFixed(2)}
              </text>
            </g>
          );
        })}

        {candles.map((c, i) => {
          const bull = c.close >= c.open;
          const color = !c.closed ? "#e6c07b" : bull ? "#3dd68c" : "#f07178";
          const xmid = x(i);
          return (
            <g key={c.bar_start}>
              <line
                x1={xmid}
                x2={xmid}
                y1={y(c.high)}
                y2={y(c.low)}
                stroke={color}
                strokeWidth={1}
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

        {/* Pattern markers (all) + levels for focused pattern */}
        {patterns.map((p, idx) => {
          const key = p.confirm_bar_start.slice(0, 19);
          let i = byTs.get(key);
          if (i == null) {
            i = candles.findIndex((c) =>
              c.bar_start.startsWith(p.confirm_bar_start.slice(0, 16)),
            );
          }
          if (i < 0 || i == null) return null;
          const xmid = x(i);
          const active = focus === p || idx === focusIndex;
          const color = p.direction === "up" ? "#61afef" : "#e6c07b";
          return (
            <g key={`${p.pattern}-${idx}`} opacity={active ? 1 : 0.35}>
              <circle
                cx={xmid}
                cy={y(p.pattern_high) - 8}
                r={active ? 6 : 4}
                fill={color}
              />
              <text
                x={xmid + 7}
                y={y(p.pattern_high) - 5}
                fill={color}
                fontSize="10"
                fontWeight={active ? 700 : 400}
              >
                {p.pattern.replace("_", " ")}
                {p.direction === "down" ? " · sell/exit" : " · buy"}
              </text>
            </g>
          );
        })}

        {focus?.entry_trigger != null && (
          <g>
            <line
              x1={pad.l}
              x2={w - pad.r}
              y1={y(focus.entry_trigger)}
              y2={y(focus.entry_trigger)}
              stroke="#3dd68c"
              strokeDasharray="4 3"
              strokeWidth={1.5}
            />
            <text
              x={w - pad.r + 4}
              y={y(focus.entry_trigger) + 3}
              fill="#3dd68c"
              fontSize="10"
            >
              entry
            </text>
          </g>
        )}
        {focus?.stop != null && (
          <g>
            <line
              x1={pad.l}
              x2={w - pad.r}
              y1={y(focus.stop)}
              y2={y(focus.stop)}
              stroke="#f07178"
              strokeDasharray="4 3"
              strokeWidth={1.5}
            />
            <text
              x={w - pad.r + 4}
              y={y(focus.stop) + 3}
              fill="#f07178"
              fontSize="10"
            >
              stop
            </text>
          </g>
        )}
        {focus?.take_profit != null && (
          <g>
            <line
              x1={pad.l}
              x2={w - pad.r}
              y1={y(focus.take_profit)}
              y2={y(focus.take_profit)}
              stroke="#61afef"
              strokeDasharray="2 4"
              strokeWidth={1.5}
            />
            <text
              x={w - pad.r + 4}
              y={y(focus.take_profit) + 3}
              fill="#61afef"
              fontSize="10"
            >
              TP
            </text>
          </g>
        )}
      </svg>
      <div className="legend">
        <span>
          <i style={{ background: "#3dd68c" }} /> Entry
        </span>
        <span>
          <i style={{ background: "#f07178" }} /> Stop
        </span>
        <span>
          <i style={{ background: "#61afef" }} /> Take profit
        </span>
        <span>
          <i style={{ background: "#e6c07b" }} /> Forming / bearish mark
        </span>
      </div>
    </div>
  );
}
