# IG candle playbook → buy / sell / stop / take-profit

Numbers below are **trade-rules-v2.6** (patterns-v2 golden), not IG official levels.

Use a **60-minute** London chart.

## When to BUY (long only)

All must be true on a **closed** 60m candle between **10:00–15:00 London**:

1. **Strong downtrend** — prior close is at least **2%** below the close 5 bars earlier.
2. **Bullish engulfing** *or* **bullish harami**
   - Engulfing: red candle, then a larger green candle whose body fully engulfs
     the prior body.
   - Harami: long red candle, then a smaller body nested inside that prior body.
3. Pattern range `(pattern_high − pattern_low) / pattern_high` ≥ **0.3%**.
4. Max **1 new trade / stock / day**.
5. **Cooloff:** if the last exit was a stop, skip the next signal.
6. **Max stops:** skip after **2** stop-outs in the window.
7. **Blocklist:** skip banks (except HSBA), defence (BA/RR), and chronic drag
   names (III, ADM, AAF, SMT, EXPN, IHG, EDV, SN, SVT, SGRO, HLN, DGE, SSE, UU,
   BHP, ANTO, CCH, ABF, INF, PRU, LGEN).

**Entry:** buy stop just above the pattern high — `entry ≈ pattern_high × 1.0005`.

## CUT LOSS

```
range = pattern_high − pattern_low
stop  = (pattern_low − 1 × range) × 0.9995
```

Do not trail to breakeven. Do not exit solely on a bearish candle.

## TAKE PROFIT

```
risk   = entry − stop
target = entry + 7 × risk            # reward:risk = 7
```

## Sizing (same for every book)

- Risk **1.5%** of cash per trade
- Cap position at **35%** of cash
- Cost gate: skip if expected 7R net ≤ 0 after Trading 212 / SDRT costs
