#!/usr/bin/env python3
"""A/B full-session (10–15 London) packs — quality filters, not hour slicing."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings, apply_broker_profile
from app.trade_rules import TRADE_RULE_PROFILES, load_trade_rules
from scripts.backtest_20d import fetch_bars, filter_last_n_trading_days
from scripts.portfolio_20d import DEFAULT_SYMBOLS, simulate_portfolio

FULL_DAY = (10, 11, 12, 13, 14, 15)
BLOCKLIST = tuple(TRADE_RULE_PROFILES["trade-rules-v2.4"]["symbol_blocklist"])
TOP10 = [s.strip() for s in DEFAULT_SYMBOLS.split(",") if s.strip()]
TOP50 = json.loads(
    Path("artifacts/portfolio_100k_top50_v22_report.json").read_text()
)["universe"]


def pack(name: str, **kw):
    r = load_trade_rules("trade-rules-v2.4")
    defaults = dict(
        version=f"ab-{name}",
        label=name,
        trade_hours_london=FULL_DAY,
        cooloff_after_stop=True,
        max_stops_per_symbol=2,
        risk_frac=0.015,
        max_position_frac=0.35,
        reward_risk=6.0,
        stop_pad_ranges=1.0,
        min_stop_pct=0.003,
        symbol_blocklist=BLOCKLIST,
        exit_on_bearish=False,
        trail_breakeven_r=None,
        min_engulf_body_ratio=1.0,
        min_downtrend_pct=0.0,
        bullish_patterns=("bullish_engulfing",),
        large_book_cash_gbp=None,
        large_book_risk_frac=None,
        large_book_max_position_frac=None,
        large_book_max_stops_per_symbol=None,
    )
    defaults.update(kw)
    return name, replace(r, **defaults)


def load_frames(symbols, days):
    period = "730d" if days > 60 else "60d"
    out = {}
    for sym in symbols:
        raw = fetch_bars(sym, interval="60m", period=period)
        if not raw.empty:
            out[sym] = filter_last_n_trading_days(raw, days)
    return out


def run(frames, rules, cash):
    settings = apply_broker_profile(Settings(starting_cash_gbp=cash), "trading212")
    risk, max_pos = rules.sizing_for_cash(cash)
    settings = settings.model_copy(
        update={
            "trade_rules_version": rules.version,
            "reward_risk": rules.reward_risk,
            "setup_expiry_bars": rules.setup_expiry_bars,
            "risk_frac": risk,
            "max_position_frac": max_pos,
        }
    )
    return simulate_portfolio(frames, settings, rules, cash)


def main() -> int:
    packs = [
        # baselines
        pack("fullday_v24clone"),  # full day, same knobs as v2.4 otherwise
        pack("fullday_noblock", symbol_blocklist=()),
        # quality engulfing
        pack("engulf1.5", min_engulf_body_ratio=1.5),
        pack("engulf2.0", min_engulf_body_ratio=2.0),
        pack("engulf2.5", min_engulf_body_ratio=2.5),
        pack("engulf3.0", min_engulf_body_ratio=3.0),
        # deeper downtrend
        pack("dt0.5%", min_downtrend_pct=0.005),
        pack("dt1.0%", min_downtrend_pct=0.01),
        pack("dt1.5%", min_downtrend_pct=0.015),
        # wider stops / range
        pack("pad1.5", stop_pad_ranges=1.5),
        pack("pad2.0", stop_pad_ranges=2.0),
        pack("minstop0.6%", min_stop_pct=0.006),
        pack("minstop1.0%", min_stop_pct=0.01),
        # RR
        pack("rr5", reward_risk=5.0),
        pack("rr7", reward_risk=7.0),
        pack("rr8", reward_risk=8.0),
        # exits / risk controls
        pack("bear_exit", exit_on_bearish=True),
        pack("max1", max_stops_per_symbol=1),
        pack("trail1R", trail_breakeven_r=1.0),
        # combos — quality first
        pack("e2+dt0.5", min_engulf_body_ratio=2.0, min_downtrend_pct=0.005),
        pack("e2+dt1", min_engulf_body_ratio=2.0, min_downtrend_pct=0.01),
        pack("e2.5+dt0.5", min_engulf_body_ratio=2.5, min_downtrend_pct=0.005),
        pack("e2+pad1.5", min_engulf_body_ratio=2.0, stop_pad_ranges=1.5),
        pack("e2+rr7", min_engulf_body_ratio=2.0, reward_risk=7.0),
        pack("e2+rr8", min_engulf_body_ratio=2.0, reward_risk=8.0),
        pack("e2+dt0.5+rr7", min_engulf_body_ratio=2.0, min_downtrend_pct=0.005, reward_risk=7.0),
        pack("e2+dt0.5+max1", min_engulf_body_ratio=2.0, min_downtrend_pct=0.005, max_stops_per_symbol=1),
        pack("e2+dt0.5+bear", min_engulf_body_ratio=2.0, min_downtrend_pct=0.005, exit_on_bearish=True),
        pack("e2.5+dt1+rr7", min_engulf_body_ratio=2.5, min_downtrend_pct=0.01, reward_risk=7.0),
        pack("e2+min0.6+rr7", min_engulf_body_ratio=2.0, min_stop_pct=0.006, reward_risk=7.0),
        pack("e2+dt0.5+pad1.5+rr7", min_engulf_body_ratio=2.0, min_downtrend_pct=0.005, stop_pad_ranges=1.5, reward_risk=7.0),
        pack("e3+dt1+rr8", min_engulf_body_ratio=3.0, min_downtrend_pct=0.01, reward_risk=8.0),
        pack("e2+dt0.5+rr7+max1", min_engulf_body_ratio=2.0, min_downtrend_pct=0.005, reward_risk=7.0, max_stops_per_symbol=1),
        pack("e2.5+dt0.5+rr7+bear", min_engulf_body_ratio=2.5, min_downtrend_pct=0.005, reward_risk=7.0, exit_on_bearish=True),
    ]

    windows = (60, 90, 120)
    cache = {}
    print("Fetching…", flush=True)
    for d in windows:
        cache[("t10", d)] = load_frames(TOP10, d)
        cache[("t50", d)] = load_frames(TOP50, d)
        print(f"  {d}d t10={len(cache[('t10',d)])} t50={len(cache[('t50',d)])}", flush=True)

    rows = []
    for name, rules in packs:
        row = {"name": name, "ok": True}
        print(f"\n=== {name} ===", flush=True)
        for d in windows:
            a = run(cache[("t10", d)], rules, 20_000)
            b = run(cache[("t50", d)], rules, 100_000)
            row[f"t10_{d}"] = a["realized_pnl_gbp"]
            row[f"t50_{d}"] = b["realized_pnl_gbp"]
            row[f"t10_{d}_n"] = a["trade_count"]
            row[f"t50_{d}_n"] = b["trade_count"]
            if a["realized_pnl_gbp"] <= 0 or b["realized_pnl_gbp"] <= 0:
                row["ok"] = False
            print(
                f"  {d}d  t10 £{a['realized_pnl_gbp']:+.0f} n={a['trade_count']}  "
                f"t50 £{b['realized_pnl_gbp']:+.0f} n={b['trade_count']}",
                flush=True,
            )
        rows.append(row)

    winners = [r for r in rows if r["ok"]]
    def score(r):
        pnls = [r[f"t10_{d}"] for d in windows] + [r[f"t50_{d}"] for d in windows]
        # prefer green with enough activity on full day
        return (min(pnls), r["t10_60_n"], sum(pnls))

    winners.sort(key=score, reverse=True)
    out = {"goal": "full-day 10-15, dual-green t10£20k + t50£100k", "winners": winners, "all": rows,
           "pick": winners[0]["name"] if winners else None}
    Path("artifacts/ab_fullday_v25.json").write_text(json.dumps(out, indent=2))
    print("\n" + "=" * 72)
    if winners:
        w = winners[0]
        print(f"PICK {w['name']}")
        for d in windows:
            print(f"  {d}d t10={w[f't10_{d}']} n={w[f't10_{d}_n']}  t50={w[f't50_{d}']} n={w[f't50_{d}_n']}")
    else:
        print("NO dual-green — need another round")
        # show least-bad by min pnl
        rows.sort(key=lambda r: min(r[f"t10_{d}"] for d in windows) + min(r[f"t50_{d}"] for d in windows), reverse=True)
        print("Top near-misses:")
        for r in rows[:8]:
            print(f"  {r['name']}: t10 60/90/120={r['t10_60']}/{r['t10_90']}/{r['t10_120']}  "
                  f"t50={r['t50_60']}/{r['t50_90']}/{r['t50_120']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
