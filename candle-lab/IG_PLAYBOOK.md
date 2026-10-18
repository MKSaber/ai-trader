# IG candle playbook → buy / sell / stop / take-profit

Qualitative shapes follow [IG Academy candlestick patterns](https://www.ig.com/uk/ig-academy/the-basics-of-technical-analysis/candlestick-patterns).
Numbers below are **trade-rules-v2** (our experiment thresholds), not IG official levels.

Use a **60-minute** London chart (not 5m).

## When to BUY (long only)

All of these must be true on a **closed** 60m candle between **10:00–15:00 London**:

1. **Downtrend context** — prior close is below the close 5 bars earlier.
2. **Bullish engulfing only** (trade-rules-v2.1) — red candle, then a larger green
   candle whose body fully engulfs the prior body.  
   *(Hammers are observed but not traded in v2.1 — they lost money on the 30d book.)*
3. Pattern range `(high − low) / high` ≥ **0.3%**.
4. You do not already have an open long in that stock today (max **1 new trade / stock / day**).

**Entry:** buy stop (or market once touched) just above the pattern candle high  
`entry ≈ high × 1.0005`.

## Where to put CUT LOSS (stop)

```
range = high − low
stop  = (low − 1 × range) × 0.9995   # one full range below the pattern low
```

If price trades through the stop, exit — do **not** also bail just because a bearish candle appears.

## Where to put TAKE PROFIT

```
risk   = entry − stop
target = entry + 5 × risk            # reward:risk = 5  (v2.1)
```

Exit at the target when hit. If neither stop nor target hits by the end of the sample, flat at last close (paper sim).

## When to SELL / stay flat

| Signal | Action |
|--------|--------|
| Stop hit | **Sell** (cut loss) |
| Take-profit hit | **Sell** (bank) |
| Bearish engulfing / shooting star while long | **Observe only** — keep stop/target |
| No valid buy checklist | **Do nothing** |

## Cost sanity (UK cash shares, e.g. Trading 212)

Before sizing, planned **5R** should still beat round-trip costs (≈ **0.5% SDRT** on the buy + small spread/slip + PTM £1.50 if consideration &gt; £10k). If not, **skip** the trade.

## One-line cheat sheet

> On 60m, in a downtrend, **11/12/14/15** London: bullish engulfing (≥0.3% range) → buy above high, stop one range below low, take profit at **5R**. Skip 10:00 and 13:00 bars.
