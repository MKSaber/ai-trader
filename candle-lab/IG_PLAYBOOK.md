# IG candle playbook → buy / sell / stop / take-profit

Numbers below are **trade-rules-v2.5** (full-day golden), not IG official levels.

Use a **60-minute** London chart.

## When to BUY (long only)

All must be true on a **closed** 60m candle between **10:00–15:00 London**:

1. **Strong downtrend** — prior close is at least **2%** below the close 5 bars earlier.
2. **Bullish engulfing** — red candle, then a larger green candle whose body fully
   engulfs the prior body.
3. Pattern range `(high − low) / high` ≥ **0.3%**.
4. Max **1 new trade / stock / day**.
5. **Cooloff:** if the last exit was a stop, skip the next signal.
6. **Max stops:** skip after **2** stop-outs in the window.
7. **Blocklist:** skip banks (except HSBA), defence (BA/RR), and chronic drag
   names (III, ADM, AAF, SMT, EXPN, IHG, EDV, SN, SVT, SGRO, HLN, DGE, SSE, UU,
   BHP, ANTO, CCH, ABF, INF, PRU, LGEN).

**Entry:** buy stop just above the pattern high — `entry ≈ high × 1.0005`.

## CUT LOSS

```
range = high − low
stop  = (low − 1 × range) × 0.9995
```

Do not trail to breakeven. Do not exit solely on a bearish candle.

## TAKE PROFIT

```
risk   = entry − stop
target = entry + 7 × risk            # reward:risk = 7
```

## Sizing (same for every book)

- Risk **1.5%** of cash · max position **35%**.

## One-line cheat sheet

> On 60m, **any London hour 10–15**, after a **≥2%** 5-bar drop: bullish engulfing
> → buy above high, stop one range below low, take profit at **7R**. Cooloff after
> a stop; max 2 stops/symbol; skip blocklisted names.
