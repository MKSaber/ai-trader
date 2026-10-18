#!/usr/bin/env python3
"""Hillclimb trade-rules for all-5-symbol positive 10d paper P&L (T212 costs)."""

from __future__ import annotations

import itertools
import json
import sys
from datetime import timezone
from pathlib import Path

import pandas as pd
import yfinance as yf
from curl_cffi import requests as curl_requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings, apply_broker_profile
from app.paper import (
    adverse_entry_price,
    entry_costs,
    exit_costs,
    simulate_long_bar,
    size_shares,
)
from app.patterns import detect_closed_patterns
from scripts.backtest_20d import (
    OpenSetup,
    _close_long,
    _force_session_flat,
    _trade_dict,
    filter_last_n_trading_days,
)

SYMBOLS = ["VOD.L", "BP.L", "HSBA.L", "GSK.L", "AZN.L"]


def fetch(symbol: str, interval: str, period: str = "60d") -> pd.DataFrame:
    ticker = yf.Ticker(symbol, session=curl_requests.Session(impersonate="chrome"))
    frame = ticker.history(
        period=period,
        interval=interval,
        auto_adjust=False,
        prepost=False,
        actions=False,
    )
    if frame is None or frame.empty:
        return pd.DataFrame()
    df = frame.reset_index()
    ts = "Datetime" if "Datetime" in df.columns else df.columns[0]
    df = df.rename(
        columns={
            ts: "bar_start",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    df["bar_start"] = pd.to_datetime(df["bar_start"], utc=True)
    df = df[["bar_start", "open", "high", "low", "close", "volume"]].dropna()
    df["closed"] = True
    return df.reset_index(drop=True)


def simulate(
    df: pd.DataFrame,
    by_confirm: dict[int, list],
    settings: Settings,
    symbol: str,
    patterns_ok: set[str],
    min_stop_pct: float,
    *,
    session_flat: bool,
    cost_gate: bool,
    max_trades_per_day: int | None,
) -> tuple[float, list[dict]]:
    cash = settings.starting_cash_gbp
    open_setup: OpenSetup | None = None
    trades: list[dict] = []
    realized = 0.0
    day_counts: dict = {}

    for i in range(len(df)):
        row = df.iloc[i]
        bar_start = pd.Timestamp(row["bar_start"]).to_pydatetime()
        if bar_start.tzinfo is None:
            bar_start = bar_start.replace(tzinfo=timezone.utc)
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        open_px = float(row["open"])
        day = bar_start.astimezone(timezone.utc).date()

        for det in by_confirm.get(i, []):
            if (
                det.direction == "up"
                and det.pattern in patterns_ok
                and open_setup is None
            ):
                if max_trades_per_day is not None:
                    if day_counts.get(day, 0) >= max_trades_per_day:
                        continue
                stop_pct = (high - low) / high if high else 0.0
                if stop_pct < min_stop_pct:
                    continue
                entry = high * (1.0 + settings.entry_buffer_frac)
                stop = low * (1.0 - settings.stop_buffer_frac)
                risk = max(entry - stop, entry * 1e-4)
                target = entry + settings.reward_risk * risk
                open_setup = OpenSetup(
                    symbol,
                    det.pattern,
                    i,
                    bar_start,
                    entry,
                    stop,
                    target,
                    i + settings.setup_expiry_bars,
                )

        if open_setup is None:
            continue

        if open_setup.status == "pending":
            if i <= open_setup.confirm_i:
                continue
            if i > open_setup.expiry_i:
                open_setup = None
                continue
            if high >= open_setup.entry_trigger:
                mid = max(open_setup.entry_trigger, open_px)
                fill = adverse_entry_price(mid, settings)
                qty = size_shares(cash, fill, open_setup.stop, settings)
                if qty <= 0:
                    open_setup = None
                    continue
                notional = qty * fill
                if cost_gate:
                    risk_ps = max(fill - open_setup.stop, fill * 1e-4)
                    expected_gross = qty * settings.reward_risk * risk_ps
                    costs = entry_costs(notional, settings).total + exit_costs(
                        qty * open_setup.target, settings
                    ).total
                    if expected_gross <= costs:
                        open_setup = None
                        continue
                cash -= notional + entry_costs(notional, settings).total
                open_setup.status = "open"
                open_setup.qty = qty
                open_setup.entry_price = fill
                open_setup.entry_i = i
                day_counts[day] = day_counts.get(day, 0) + 1
        elif open_setup.status == "open":
            if open_setup.entry_i == i:
                continue
            simr = simulate_long_bar(
                open_setup.entry_price,
                open_setup.stop,
                open_setup.target,
                high,
                low,
                close,
            )
            force = session_flat and _force_session_flat(bar_start)
            if simr is None and not force:
                continue
            if simr is None:
                exit_mid, reason, amb = close, "session_flat", False
            else:
                exit_mid, reason, amb = simr.exit_mid, simr.reason, simr.ambiguous
            open_setup, cash, pnl = _close_long(
                open_setup, exit_mid, reason, amb, i, cash, settings
            )
            realized += pnl
            trades.append(_trade_dict(open_setup))
            open_setup = None

    if open_setup and open_setup.status == "open":
        open_setup, cash, pnl = _close_long(
            open_setup,
            float(df.iloc[-1]["close"]),
            "end_of_series",
            False,
            len(df) - 1,
            cash,
            settings,
        )
        realized += pnl
        trades.append(_trade_dict(open_setup))
    return realized, trades


def main() -> int:
    days = 10
    cache: dict[str, dict[str, tuple[pd.DataFrame, dict]]] = {}
    for interval in ("5m", "60m"):
        cache[interval] = {}
        for sym in SYMBOLS:
            print(f"fetch {interval} {sym}", flush=True)
            raw = fetch(sym, interval)
            df = filter_last_n_trading_days(raw, days)
            dets = detect_closed_patterns(df) if len(df) else []
            by: dict[int, list] = {}
            for d in dets:
                by.setdefault(d.confirm_index, []).append(d)
            cache[interval][sym] = (df, by)
            print(f"  bars={len(df)} dets={len(dets)}", flush=True)

    base = apply_broker_profile(Settings(starting_cash_gbp=100_000.0), "trading212")
    results = []
    grid = list(
        itertools.product(
            ("5m", "60m"),
            [3.0, 4.0, 5.0, 6.0],
            [0.0, 0.0025, 0.005],
            [3, 8],
            [
                frozenset({"hammer"}),
                frozenset({"bullish_engulfing"}),
                frozenset({"bullish_engulfing", "hammer"}),
            ],
            [True],  # cost_gate on (skip uneconomic)
            [False],  # no forced session flat — let stop/target work
            [1],  # max 1 new trade/day/symbol
            [0.05, 0.1],  # max_position_frac
            [0.005],  # risk_frac
        )
    )
    print(f"grid size {len(grid)}", flush=True)

    for (
        interval,
        rr,
        min_stop,
        expiry,
        pats,
        cost_gate,
        session_flat,
        max_day,
        max_pos,
        risk_frac,
    ) in grid:
        settings = base.model_copy(
            update={
                "reward_risk": rr,
                "setup_expiry_bars": expiry,
                "max_position_frac": max_pos,
                "risk_frac": risk_frac,
            }
        )
        pnls: dict[str, float] = {}
        ntr = 0
        for sym, (df, by) in cache[interval].items():
            pnl, tr = simulate(
                df,
                by,
                settings,
                sym,
                set(pats),
                min_stop,
                session_flat=session_flat,
                cost_gate=cost_gate,
                max_trades_per_day=max_day,
            )
            pnls[sym] = pnl
            ntr += len(tr)
        if ntr == 0:
            continue
        npos = sum(1 for v in pnls.values() if v > 0)
        all_pos = npos == 5
        total = sum(pnls.values())
        results.append(
            {
                "all_pos": all_pos,
                "npos": npos,
                "total": total,
                "trades": ntr,
                "interval": interval,
                "reward_risk": rr,
                "min_stop_pct": min_stop,
                "expiry": expiry,
                "patterns": sorted(pats),
                "cost_gate": cost_gate,
                "session_flat": session_flat,
                "max_trades_per_day": max_day,
                "max_position_frac": max_pos,
                "risk_frac": risk_frac,
                "pnls": {k: round(v, 2) for k, v in pnls.items()},
            }
        )

    results.sort(key=lambda x: (x["all_pos"], x["npos"], x["total"]), reverse=True)
    out = Path("artifacts") / "hillclimb_10d_trading212.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"top": results[:50], "n_configs": len(results)}, indent=2))
    print(f"kept configs with trades: {len(results)}", flush=True)
    print(f"all-positive: {sum(1 for r in results if r['all_pos'])}", flush=True)
    for r in results[:25]:
        print(
            f"npos={r['npos']} all={r['all_pos']} tot={r['total']:8.1f} n={r['trades']:3} "
            f"{r['interval']} rr={r['reward_risk']} stop>={r['min_stop_pct']} "
            f"exp={r['expiry']} pats={r['patterns']} gate={r['cost_gate']} "
            f"flat={r['session_flat']} maxday={r['max_trades_per_day']} "
            f"maxpos={r['max_position_frac']} risk={r['risk_frac']}",
            flush=True,
        )
        print(f"  {r['pnls']}", flush=True)
    print(f"wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
