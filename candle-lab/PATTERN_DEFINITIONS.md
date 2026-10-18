# Candlestick pattern definitions — Live Candle Pattern Test

**Reference (qualitative only, not a data source):**  
https://www.ig.com/uk/ig-academy/the-basics-of-technical-analysis/candlestick-patterns  
Accessed successfully for this experiment.

IG provides **qualitative** shapes and contexts. Numerical thresholds below are
**experiment assumptions** (detector version `patterns-v1`), not official IG
numbers.

## Scope for patterns-v1

| Pattern | Directional hypothesis | Role in paper engine |
|---------|------------------------|----------------------|
| Bullish engulfing | Up | Long setup candidate |
| Bearish engulfing | Down | Observation / long-exit signal only |
| Hammer | Up (in downtrend) | Long setup candidate |
| Shooting star | Down (in uptrend) | Observation / long-exit signal only |

## IG qualitative definitions (paraphrased from the page)

### Hammer
When seen during a **downtrend**, can signify the market is about to go up.
For a particularly strong signal, the **lower wick must be at least twice as
long as the body** and there should be **little or no upper wick**. Body colour
is not especially important; green tends to be more bullish than red.

### Shooting star
A **reversal candle during an uptrend**. Same shape as the inverted hammer
(long upper wick, short/absent lower wick). Listed among patterns that indicate
a market is likely to go into a **downtrend**.

### Bullish engulfing
A **red candle immediately followed by a larger green candle**, suggesting a
strong move upwards. The second candle’s body is so large it **engulfs** the
former candle.

### Bearish engulfing
A **smaller green candle engulfed by a larger red one** — signifying a strong
move lower.

## Mathematical implementation (`patterns-v1`)

Notation for a closed bar `i` (Europe/London session):  
`O,H,L,C` = open, high, low, close.  
`body = |C - O|`, `upper = H - max(O,C)`, `lower = min(O,C) - L`.  
`eps` = relative equality tolerance = `max(1e-8, 1e-4 * mid)` where
`mid = (H+L)/2` (zero-range bars: if `H <= L + eps`, bar is skipped).

### Preceding trend (experiment assumption)

IG requires context (downtrend for hammer, uptrend for shooting star) but does
not define the lookback. We use:

- `trend_lookback = 5` completed bars before the pattern’s first bar.
- **Downtrend:** `C[i-1] < C[i-1-trend_lookback]` (simple close comparison).
- **Uptrend:** `C[i-1] > C[i-1-trend_lookback]`.

Engulfing patterns do not require this trend filter in `patterns-v1` (IG text
emphasises the two-candle structure); trend is recorded as context only.

### Bullish engulfing (confirmed on bar `i` close)

Requires bars `i-1` and `i` both closed.

1. Prior bearish: `C[i-1] < O[i-1] - eps`
2. Current bullish: `C[i] > O[i] + eps`
3. Body engulfs prior body: `O[i] <= C[i-1] + eps` and `C[i] >= O[i-1] - eps`
4. Current body strictly larger: `body[i] > body[i-1] + eps`

Minimum history: `2` closed bars (+ warm-up for charts).

### Bearish engulfing (bar `i`)

1. Prior bullish: `C[i-1] > O[i-1] + eps`
2. Current bearish: `C[i] < O[i] - eps`
3. `O[i] >= C[i-1] - eps` and `C[i] <= O[i-1] + eps`
4. `body[i] > body[i-1] + eps`

### Hammer (single bar `i`, in downtrend)

1. Downtrend filter true at `i`
2. `body[i] > eps` (reject pure doji as hammer in v1)
3. `lower[i] >= 2 * body[i]` (IG: lower wick at least twice the body)
4. `upper[i] <= max(eps, 0.25 * body[i])` (IG: little or no upper wick;
   `0.25` is an experiment assumption)

### Shooting star (single bar `i`, in uptrend)

1. Uptrend filter true at `i`
2. `body[i] > eps`
3. `upper[i] >= 2 * body[i]`
4. `lower[i] <= max(eps, 0.25 * body[i])`

## Timing rules

- Detection runs **only on closed** 5-minute candles.
- The forming (incomplete) candle is **provisional** and never emits a final
  signal.
- Swing/trend inputs use only bars available at confirmation time — never
  backdated after later bars arrive.

## Detector versioning

Config blob `detector_version: patterns-v1` is stored immutably on every signal.
Rule changes require `patterns-v2` and a new experiment id.
