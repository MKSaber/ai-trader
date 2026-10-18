# IG candle playbook → buy / sell / stop / take-profit

Qualitative shapes follow [IG Academy candlestick patterns](https://www.ig.com/uk/ig-academy/the-basics-of-technical-analysis/candlestick-patterns).
Numbers below are **trade-rules-v2.4** (golden unified formula), not IG official levels.

Use a **60-minute** London chart (not 5m).

## When to BUY (long only)

All of these must be true on a **closed** 60m candle at **15:00 London only**:

1. **Downtrend context** — prior close is below the close 5 bars earlier.
2. **Bullish engulfing only** — red candle, then a larger green candle whose
   body fully engulfs the prior body.
3. Pattern range `(high − low) / high` ≥ **0.3%**.
4. Max **1 new trade / stock / day**.
5. **Cooloff:** if the last exit on this symbol was a stop, skip the next signal.
6. **Max stops:** skip the symbol after **2** stop-outs in the window.
7. **Blocklist:** skip banks (except HSBA), defence (BA/RR), and chronic drag
   names (III, ADM, AAF, SMT, EXPN, IHG, EDV, SN, SVT, SGRO, HLN, DGE, SSE, UU,
   BHP, ANTO, CCH, ABF, INF, PRU, LGEN).

**Entry:** buy stop (or market once touched) just above the pattern candle high  
`entry ≈ high × 1.0005`.

## Where to put CUT LOSS (stop)

```
range = high − low
stop  = (low − 1 × range) × 0.9995   # one full range below the pattern low
```

If price trades through the stop, exit — do **not** trail to breakeven.

## Where to put TAKE PROFIT

```
risk   = entry − stop
target = entry + 6 × risk            # reward:risk = 6
```

## Sizing (same for every book)

- Risk **1.5%** of cash per trade.
- Cap any single name at **35%** of cash.

## When to SELL / stay flat

| Signal | Action |
|--------|--------|
| Stop hit | **Sell** (cut loss) + cooloff next signal |
| Take-profit hit | **Sell** (bank) |
| Bearish engulfing / shooting star while long | **Observe only** — keep stop/target |
| No valid buy checklist | **Do nothing** |

## Cost sanity (UK cash shares, e.g. Trading 212)

Before sizing, planned **6R** should still beat round-trip costs (≈ **0.5% SDRT** on the buy + small spread/slip + PTM £1.50 if consideration &gt; £10k). If not, **skip** the trade.

## One-line cheat sheet

> On 60m, in a downtrend, **15:00 London only**: bullish engulfing (≥0.3% range) → buy above high, stop one range below low, take profit at **6R**. Cooloff after a stop; max 2 stops/symbol; skip blocklisted drag names. Size **1.5% / 35%** on every book.
