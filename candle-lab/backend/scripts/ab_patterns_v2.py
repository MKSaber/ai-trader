#!/usr/bin/env python3
"""A/B patterns-v2 detectors + confirmations inside the trade-rules-v2.5 shell.

Baseline: v2.5 knobs (hours 10-15, RR=7, downtrend≥2%, blocklist, engulfing).
Variants add piercing / harami / morning-star / three-outside-up and optional
volume / next-open / upper-half confirmations.
"""

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

BLOCKLIST = tuple(TRADE_RULE_PROFILES["trade-rules-v2.5"]["symbol_blocklist"])
TOP10 = [s.strip() for s in DEFAULT_SYMBOLS.split(",") if s.strip()]
TOP50 = json.loads(
    Path("artifacts/portfolio_100k_top50_v22_report.json").read_text()
)["universe"]

ENGULF = ("bullish_engulfing",)
NEW = (
    "piercing_line",
    "bullish_harami",
    "morning_star",
    "three_outside_up",
)
ALL = ENGULF + NEW
CONFIRMED = ("morning_star", "three_outside_up")  # built-in 3rd-bar confirm


def pack(name: str, **kw):
    r = load_trade_rules("trade-rules-v2.5")
    defaults = dict(
        version=f"ab-pv2-{name}",
        label=name,
        trade_hours_london=(10, 11, 12, 13, 14, 15),
        cooloff_after_stop=True,
        max_stops_per_symbol=2,
        risk_frac=0.015,
        max_position_frac=0.35,
        reward_risk=7.0,
        stop_pad_ranges=1.0,
        min_stop_pct=0.003,
        symbol_blocklist=BLOCKLIST,
        exit_on_bearish=False,
        trail_breakeven_r=None,
        min_engulf_body_ratio=1.0,
        min_downtrend_pct=0.02,
        bullish_patterns=ENGULF,
        min_volume_ratio=0.0,
        require_next_open_confirm=False,
        require_close_in_upper_half=False,
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
        # control
        pack("v25_engulf"),
        # single new patterns (+ engulfing kept as core)
        pack("engulf+pierce", bullish_patterns=ENGULF + ("piercing_line",)),
        pack("engulf+harami", bullish_patterns=ENGULF + ("bullish_harami",)),
        pack("engulf+ms", bullish_patterns=ENGULF + ("morning_star",)),
        pack("engulf+3ou", bullish_patterns=ENGULF + ("three_outside_up",)),
        pack("all_new", bullish_patterns=ALL),
        pack("confirmed_only", bullish_patterns=CONFIRMED),
        pack("pierce_only", bullish_patterns=("piercing_line",)),
        # volume confirm
        pack("engulf+vol1.2", min_volume_ratio=1.2),
        pack("engulf+vol1.5", min_volume_ratio=1.5),
        pack("all+vol1.2", bullish_patterns=ALL, min_volume_ratio=1.2),
        pack("all+vol1.5", bullish_patterns=ALL, min_volume_ratio=1.5),
        pack("engulf+3ou+vol1.2", bullish_patterns=ENGULF + ("three_outside_up",), min_volume_ratio=1.2),
        # next-open confirm
        pack("engulf+next", require_next_open_confirm=True),
        pack("all+next", bullish_patterns=ALL, require_next_open_confirm=True),
        pack("engulf+vol1.2+next", min_volume_ratio=1.2, require_next_open_confirm=True),
        pack("all+vol1.2+next", bullish_patterns=ALL, min_volume_ratio=1.2, require_next_open_confirm=True),
        # upper-half close
        pack("engulf+uhalf", require_close_in_upper_half=True),
        pack("all+uhalf", bullish_patterns=ALL, require_close_in_upper_half=True),
        pack("all+vol1.2+uhalf", bullish_patterns=ALL, min_volume_ratio=1.2, require_close_in_upper_half=True),
        # denser combos
        pack(
            "all+vol1.2+next+uhalf",
            bullish_patterns=ALL,
            min_volume_ratio=1.2,
            require_next_open_confirm=True,
            require_close_in_upper_half=True,
        ),
        pack(
            "engulf+3ou+vol1.2+next",
            bullish_patterns=ENGULF + ("three_outside_up",),
            min_volume_ratio=1.2,
            require_next_open_confirm=True,
        ),
        pack(
            "confirmed+vol1.2",
            bullish_patterns=CONFIRMED,
            min_volume_ratio=1.2,
        ),
        pack(
            "pierce+vol1.2+next",
            bullish_patterns=("piercing_line",),
            min_volume_ratio=1.2,
            require_next_open_confirm=True,
        ),
    ]

    windows = (60, 90, 120)
    cache = {}
    print("Fetching…", flush=True)
    for d in windows:
        cache[("t10", d)] = load_frames(TOP10, d)
        cache[("t50", d)] = load_frames(TOP50, d)
        print(
            f"  {d}d t10={len(cache[('t10', d)])} t50={len(cache[('t50', d)])}",
            flush=True,
        )

    rows = []
    for name, rules in packs:
        row = {"name": name, "ok": True, "patterns": list(rules.bullish_patterns)}
        print(f"\n=== {name} ===", flush=True)
        for d in windows:
            a = run(cache[("t10", d)], rules, 20_000)
            b = run(cache[("t50", d)], rules, 100_000)
            row[f"t10_{d}"] = a["realized_pnl_gbp"]
            row[f"t50_{d}"] = b["realized_pnl_gbp"]
            row[f"t10_{d}_n"] = a["trade_count"]
            row[f"t50_{d}_n"] = b["trade_count"]
            row[f"t10_{d}_pat"] = a.get("pattern_totals", {})
            row[f"t50_{d}_pat"] = b.get("pattern_totals", {})
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
        return (min(pnls), r["t10_60_n"], sum(pnls))

    winners.sort(key=score, reverse=True)
    out = {
        "goal": "patterns-v2 dual-green t10£20k + t50£100k in v2.5 shell",
        "detector": "patterns-v2",
        "shell": "trade-rules-v2.5",
        "winners": winners,
        "all": rows,
        "pick": winners[0]["name"] if winners else None,
    }
    Path("artifacts/ab_patterns_v2.json").write_text(json.dumps(out, indent=2, default=str))
    print("\n" + "=" * 72)
    if winners:
        w = winners[0]
        print(f"PICK {w['name']}")
        for d in windows:
            print(
                f"  {d}d t10={w[f't10_{d}']} n={w[f't10_{d}_n']}  "
                f"t50={w[f't50_{d}']} n={w[f't50_{d}_n']}"
            )
    else:
        print("NO dual-green — need another round")
        rows.sort(
            key=lambda r: min(r[f"t10_{d}"] for d in windows)
            + min(r[f"t50_{d}"] for d in windows),
            reverse=True,
        )
        print("Top near-misses:")
        for r in rows[:10]:
            print(
                f"  {r['name']}: t10 60/90/120="
                f"{r['t10_60']}/{r['t10_90']}/{r['t10_120']}  "
                f"t50={r['t50_60']}/{r['t50_90']}/{r['t50_120']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
