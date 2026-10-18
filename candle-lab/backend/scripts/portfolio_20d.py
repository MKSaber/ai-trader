#!/usr/bin/env python3
"""Shared-cash portfolio paper sim for trade-rules-v2.

Starts with one GBP cash pot (default £20,000), walks 60m bars across a
larger LSE universe chronologically, and reports final equity after N days.

Usage:
  python scripts/portfolio_20d.py --days 20 --cash 20000 --broker trading212
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import BROKER_PROFILES, Settings, apply_broker_profile
from app.paper import (
    adverse_entry_price,
    entry_costs,
    exit_costs,
    simulate_long_bar,
    size_shares,
)
from app.patterns import DETECTOR_VERSION, detect_closed_patterns, in_downtrend
from app.trade_rules import (
    expected_net_at_target,
    load_trade_rules,
    setup_levels,
)
from scripts.backtest_20d import (
    LONDON,
    OpenSetup,
    _close_long,
    _force_session_flat,
    _trade_dict,
    fetch_bars,
    filter_last_n_trading_days,
)

# Top LSE / FTSE megacaps (Yahoo .L). Weak day-trade names from the
# 15-name scan (BARC, LLOY, RR, GLEN, VOD) dropped; RR/GLEN replaced by
# next large liquid names NG + REL despite RR/GLEN ranking in raw mcap top 10.
DEFAULT_SYMBOLS = (
    "HSBA.L,AZN.L,SHEL.L,RIO.L,BATS.L,"
    "ULVR.L,BP.L,GSK.L,NG.L,REL.L"
)


def simulate_portfolio(
    frames: dict[str, pd.DataFrame],
    settings: Settings,
    rules,
    starting_cash: float,
) -> dict:
    """One shared cash book; at most one open setup per symbol."""
    # Precompute detections
    by_symbol: dict[str, dict[int, list]] = {}
    pattern_totals: dict[str, int] = defaultdict(int)
    for sym, df in frames.items():
        dets = detect_closed_patterns(df) if len(df) else []
        by: dict[int, list] = {}
        for d in dets:
            by.setdefault(d.confirm_index, []).append(d)
            pattern_totals[d.pattern] += 1
        by_symbol[sym] = by

    # Event list: (timestamp, symbol, bar_index)
    events: list[tuple[pd.Timestamp, str, int]] = []
    for sym, df in frames.items():
        for i, ts in enumerate(df["bar_start"]):
            events.append((pd.Timestamp(ts), sym, i))
    events.sort(key=lambda e: (e[0], e[1]))

    cash = float(starting_cash)
    open_by_sym: dict[str, OpenSetup] = {}
    day_trade_counts: dict[tuple[str, object], int] = {}
    trades: list[dict] = []
    equity_curve: list[dict] = []
    # v2.2 / v2.3 risk controls (max stops may scale with book size)
    cooloff_sym: set[str] = set()  # skip next signal after a stop
    stop_counts: dict[str, int] = defaultdict(int)
    initial_stop: dict[str, float] = {}
    max_stops_limit = (
        rules.max_stops_for_cash(starting_cash)
        if hasattr(rules, "max_stops_for_cash")
        else getattr(rules, "max_stops_per_symbol", None)
    )

    last_close: dict[str, float] = {}

    for ts, sym, i in events:
        df = frames[sym]
        row = df.iloc[i]
        bar_start = pd.Timestamp(row["bar_start"]).to_pydatetime()
        if bar_start.tzinfo is None:
            bar_start = bar_start.replace(tzinfo=timezone.utc)
        local = bar_start.astimezone(LONDON)
        day = local.date()
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        open_px = float(row["open"])
        last_close[sym] = close

        setup = open_by_sym.get(sym)

        # --- manage open position first ---
        if setup and setup.status == "open":
            if setup.entry_i is not None and i == setup.entry_i:
                pass
            else:
                # Trail stop to breakeven after +N R favorable excursion
                trail_r = getattr(rules, "trail_breakeven_r", None)
                if trail_r is not None and sym in initial_stop:
                    risk0 = max(setup.entry_price - initial_stop[sym], setup.entry_price * 1e-4)
                    if high >= setup.entry_price + trail_r * risk0:
                        setup.stop = max(setup.stop, setup.entry_price)
                sim = simulate_long_bar(
                    setup.entry_price,
                    setup.stop,
                    setup.target,
                    high,
                    low,
                    close,
                )
                force = rules.session_flat and _force_session_flat(bar_start)
                if sim is not None or force:
                    if sim is None:
                        exit_mid, reason, amb = close, "session_flat", False
                    else:
                        exit_mid, reason, amb = (
                            sim.exit_mid,
                            sim.reason,
                            sim.ambiguous,
                        )
                    setup, cash, _pnl = _close_long(
                        setup, exit_mid, reason, amb, i, cash, settings
                    )
                    trades.append(_trade_dict(setup))
                    if reason.startswith("stop"):
                        if getattr(rules, "cooloff_after_stop", False):
                            cooloff_sym.add(sym)
                        stop_counts[sym] += 1
                    else:
                        cooloff_sym.discard(sym)
                    initial_stop.pop(sym, None)
                    del open_by_sym[sym]
                    setup = None

        # --- new signals on this closed bar ---
        for det in by_symbol[sym].get(i, []):
            if setup is not None:
                break
            if det.direction != "up" or det.pattern not in rules.bullish_set:
                continue
            if sym in getattr(rules, "blocklist_set", set()):
                continue
            if (
                rules.trade_hours_london is not None
                and local.hour not in rules.trade_hours_london
            ):
                continue
            key = (sym, day)
            if (
                rules.max_trades_per_day is not None
                and day_trade_counts.get(key, 0) >= rules.max_trades_per_day
            ):
                continue
            if getattr(rules, "cooloff_after_stop", False) and sym in cooloff_sym:
                # Consume cooloff: skip this signal, allow later ones
                cooloff_sym.discard(sym)
                continue
            if max_stops_limit is not None and stop_counts[sym] >= max_stops_limit:
                continue
            if rules.require_downtrend and not in_downtrend(df, i):
                continue
            stop_pct = (high - low) / high if high else 0.0
            if stop_pct < rules.min_stop_pct:
                continue
            entry, stop, target = setup_levels(
                high,
                low,
                entry_buffer_frac=settings.entry_buffer_frac,
                stop_buffer_frac=settings.stop_buffer_frac,
                reward_risk=rules.reward_risk,
                stop_pad_ranges=rules.stop_pad_ranges,
            )
            setup = OpenSetup(
                symbol=sym,
                pattern=det.pattern,
                confirm_i=i,
                confirm_ts=bar_start,
                entry_trigger=entry,
                stop=stop,
                target=target,
                expiry_i=i + rules.setup_expiry_bars,
            )
            open_by_sym[sym] = setup

        # --- pending entry fill ---
        setup = open_by_sym.get(sym)
        if setup and setup.status == "pending":
            if i <= setup.confirm_i:
                continue
            if i > setup.expiry_i:
                setup.status = "expired"
                del open_by_sym[sym]
                continue
            if high >= setup.entry_trigger:
                mid = max(setup.entry_trigger, open_px)
                fill_px = adverse_entry_price(mid, settings)
                qty = size_shares(cash, fill_px, setup.stop, settings)
                if qty <= 0:
                    setup.status = "expired"
                    del open_by_sym[sym]
                    continue
                notional = qty * fill_px
                ec = entry_costs(notional, settings)
                xc = exit_costs(qty * setup.target, settings)
                if rules.cost_gate:
                    net = expected_net_at_target(
                        qty,
                        fill_px,
                        setup.stop,
                        setup.target,
                        rules.reward_risk,
                        ec.total,
                        xc.total,
                    )
                    if net <= 0:
                        setup.status = "expired"
                        del open_by_sym[sym]
                        continue
                cash -= notional + ec.total
                setup.status = "open"
                setup.qty = qty
                setup.entry_price = fill_px
                setup.entry_i = i
                initial_stop[sym] = setup.stop
                day_trade_counts[(sym, day)] = day_trade_counts.get((sym, day), 0) + 1

        # light equity sample each event hour
        if local.minute == 0:
            exposure = sum(
                s.qty * last_close.get(s.symbol, s.entry_price)
                for s in open_by_sym.values()
                if s.status == "open"
            )
            equity_curve.append(
                {
                    "ts": bar_start.isoformat(),
                    "cash": round(cash, 2),
                    "open_positions": sum(
                        1 for s in open_by_sym.values() if s.status == "open"
                    ),
                    "equity": round(cash + exposure, 2),
                }
            )

    # Flatten leftovers at last closes
    for sym, setup in list(open_by_sym.items()):
        if setup.status != "open":
            continue
        df = frames[sym]
        px = float(df.iloc[-1]["close"])
        setup, cash, _ = _close_long(
            setup, px, "end_of_series", False, len(df) - 1, cash, settings
        )
        trades.append(_trade_dict(setup))
        del open_by_sym[sym]

    final_equity = cash
    by_sym_pnl: dict[str, float] = defaultdict(float)
    for t in trades:
        by_sym_pnl[t["symbol"]] += t["pnl_gbp"]

    return {
        "starting_cash_gbp": starting_cash,
        "final_cash_gbp": round(final_equity, 2),
        "realized_pnl_gbp": round(final_equity - starting_cash, 2),
        "return_pct": round(100.0 * (final_equity - starting_cash) / starting_cash, 4),
        "trade_count": len(trades),
        "wins": sum(1 for t in trades if t["pnl_gbp"] >= 0),
        "losses": sum(1 for t in trades if t["pnl_gbp"] < 0),
        "pattern_totals": dict(pattern_totals),
        "pnl_by_symbol": {k: round(v, 2) for k, v in sorted(by_sym_pnl.items())},
        "trades": trades,
        "equity_curve_tail": equity_curve[-40:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Shared £ portfolio candle paper sim")
    parser.add_argument("--days", type=int, default=20)
    parser.add_argument("--cash", type=float, default=20_000.0)
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--broker", default="trading212", choices=sorted(BROKER_PROFILES))
    parser.add_argument("--rules", default="trade-rules-v2.4")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    rules = load_trade_rules(args.rules)
    settings = apply_broker_profile(
        Settings(starting_cash_gbp=args.cash),
        args.broker,
    )
    risk_frac, max_position_frac = rules.sizing_for_cash(args.cash)
    settings = settings.model_copy(
        update={
            "trade_rules_version": rules.version,
            "reward_risk": rules.reward_risk,
            "setup_expiry_bars": rules.setup_expiry_bars,
            "max_position_frac": max_position_frac,
            "risk_frac": risk_frac,
        }
    )

    frames: dict[str, pd.DataFrame] = {}
    feed = []
    for sym in symbols:
        print(f"\n=== {sym} ===", flush=True)
        # Intraday Yahoo: use 60d for ≤60 sessions; longer history via 730d when needed
        period = "730d" if args.days > 60 else "60d"
        raw = fetch_bars(sym, interval=rules.interval, period=period)
        if raw.empty:
            feed.append({"symbol": sym, "healthy": False})
            continue
        df = filter_last_n_trading_days(raw, args.days)
        frames[sym] = df
        feed.append(
            {
                "symbol": sym,
                "healthy": True,
                "bars": len(df),
                "days": int(df["bar_start"].dt.tz_convert(LONDON).dt.date.nunique()),
                "first": str(df["bar_start"].iloc[0]) if len(df) else None,
                "last": str(df["bar_start"].iloc[-1]) if len(df) else None,
            }
        )

    result = simulate_portfolio(frames, settings, rules, args.cash)
    report = {
        "detector_version": DETECTOR_VERSION,
        "trade_rules_version": rules.version,
        "trade_rules_label": rules.label,
        "interval": rules.interval,
        "cost_profile": args.broker,
        "days_requested": args.days,
        "symbols": symbols,
        "symbols_with_data": list(frames.keys()),
        "feed": feed,
        "playbook": "candle-lab/IG_PLAYBOOK.md",
        **result,
        "disclaimer": (
            "Shared-cash paper sim on delayed Yahoo 60m bars with named trade rules "
            "and Trading 212 / GOV.UK costs. Not live broker execution. "
            "v2.4 golden unified formula (RR=6 + blocklist + static 1.5%/35%) "
            "— one profile for all books; research only."
        ),
    }

    out = (
        Path(args.out)
        if args.out
        else Path("artifacts")
        / f"portfolio_{args.days}d_cash{int(args.cash)}_{args.broker}_summary.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    # Compact: drop full equity curve noise already tailed
    out.write_text(json.dumps(report, indent=2, default=str))

    print("=" * 72)
    print(f"Shared portfolio — £{args.cash:,.0f} start · {args.days} days · {rules.version}")
    print("=" * 72)
    print(f"Symbols with data: {len(frames)}/{len(symbols)}")
    print(f"Trades: {result['trade_count']}  wins={result['wins']}  losses={result['losses']}")
    print(f"Starting cash: £{args.cash:,.2f}")
    print(f"Final cash:    £{result['final_cash_gbp']:,.2f}")
    print(f"P&L:           £{result['realized_pnl_gbp']:,.2f} ({result['return_pct']:+.2f}%)")
    print("-" * 72)
    for sym, pnl in result["pnl_by_symbol"].items():
        print(f"  {sym}: £{pnl:,.2f}")
    print("-" * 72)
    print(report["disclaimer"])
    print(f"Wrote {out.resolve()}")
    print(f"IG buy/sell/TP/SL: see candle-lab/IG_PLAYBOOK.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
