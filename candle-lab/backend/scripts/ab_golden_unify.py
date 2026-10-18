#!/usr/bin/env python3
"""A/B unified (no cash-fork) rule packs across top-10 £20k and top-50 £100k."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings, apply_broker_profile
from app.trade_rules import TRADE_RULE_PROFILES, TradeRules, load_trade_rules
from scripts.backtest_20d import fetch_bars, filter_last_n_trading_days
from scripts.portfolio_20d import DEFAULT_SYMBOLS, simulate_portfolio

TOP50 = json.loads(
    Path("artifacts/portfolio_100k_top50_v22_report.json").read_text()
)["universe"]
TOP10 = [s.strip() for s in DEFAULT_SYMBOLS.split(",") if s.strip()]

# Drag blocklist from v2.3 root-cause (same for every book — part of the formula)
BLOCKLIST = tuple(TRADE_RULE_PROFILES["trade-rules-v2.3"]["symbol_blocklist"])

# Lighter blocklist: only worst cohorts
BLOCKLIST_LIGHT = (
    "LLOY.L",
    "BARC.L",
    "NWG.L",
    "STAN.L",
    "BA.L",
    "RR.L",
    "III.L",
    "ADM.L",
    "AAF.L",
    "EDV.L",
    "SN.L",
    "BHP.L",
)


def base_v22() -> TradeRules:
    return load_trade_rules("trade-rules-v2.2")


def pack(
    name: str,
    *,
    blocklist: tuple[str, ...] = (),
    max_stops: int | None = 2,
    risk: float = 0.015,
    max_pos: float = 0.35,
    hours: tuple[int, ...] = (15,),
    rr: float = 5.0,
    cooloff: bool = True,
) -> tuple[str, TradeRules]:
    r = base_v22()
    r = replace(
        r,
        version=f"ab-{name}",
        label=name,
        trade_hours_london=hours,
        cooloff_after_stop=cooloff,
        max_stops_per_symbol=max_stops,
        risk_frac=risk,
        max_position_frac=max_pos,
        reward_risk=rr,
        symbol_blocklist=blocklist,
        # force no cash forks
        large_book_cash_gbp=None,
        large_book_risk_frac=None,
        large_book_max_position_frac=None,
        large_book_max_stops_per_symbol=None,
    )
    return name, r


def load_frames(symbols: list[str], days: int) -> dict:
    period = "730d" if days > 60 else "60d"
    frames = {}
    for sym in symbols:
        raw = fetch_bars(sym, interval="60m", period=period)
        if raw.empty:
            continue
        frames[sym] = filter_last_n_trading_days(raw, days)
    return frames


def run(frames, rules: TradeRules, cash: float) -> dict:
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
        pack("v22_plain"),
        pack("v22+block", blocklist=BLOCKLIST),
        pack("v22+block_light", blocklist=BLOCKLIST_LIGHT),
        pack("block+max1", blocklist=BLOCKLIST, max_stops=1),
        pack("block+r1.0/p25", blocklist=BLOCKLIST, risk=0.01, max_pos=0.25),
        pack("block+r1.0/p25+max1", blocklist=BLOCKLIST, risk=0.01, max_pos=0.25, max_stops=1),
        pack("block+r0.8/p15", blocklist=BLOCKLIST, risk=0.008, max_pos=0.15),
        pack("block+r0.8/p15+max1", blocklist=BLOCKLIST, risk=0.008, max_pos=0.15, max_stops=1),
        pack("block+r1.2/p20", blocklist=BLOCKLIST, risk=0.012, max_pos=0.20),
        pack("block+r1.2/p20+max1", blocklist=BLOCKLIST, risk=0.012, max_pos=0.20, max_stops=1),
        pack("light+r1.0/p25+max1", blocklist=BLOCKLIST_LIGHT, risk=0.01, max_pos=0.25, max_stops=1),
        pack("light+r1.5/p35+max1", blocklist=BLOCKLIST_LIGHT, max_stops=1),
        pack("block+rr6", blocklist=BLOCKLIST, rr=6.0),
        pack("block+rr6+max1", blocklist=BLOCKLIST, rr=6.0, max_stops=1),
        pack("block+r1.0/p20+max1", blocklist=BLOCKLIST, risk=0.01, max_pos=0.20, max_stops=1),
    ]

    windows = (60, 90, 120)
    cache: dict[tuple[str, int], dict] = {}

    print("Fetching frames…", flush=True)
    for days in windows:
        cache[("top10", days)] = load_frames(TOP10, days)
        cache[("top50", days)] = load_frames(TOP50, days)
        print(
            f"  {days}d top10={len(cache[('top10', days)])} top50={len(cache[('top50', days)])}",
            flush=True,
        )

    rows = []
    for name, rules in packs:
        row = {"name": name, "ok": True}
        print(f"\n=== {name} ===", flush=True)
        for days in windows:
            t10 = run(cache[("top10", days)], rules, 20_000)
            t50 = run(cache[("top50", days)], rules, 100_000)
            row[f"t10_{days}"] = t10["realized_pnl_gbp"]
            row[f"t50_{days}"] = t50["realized_pnl_gbp"]
            row[f"t10_{days}_n"] = t10["trade_count"]
            row[f"t50_{days}_n"] = t50["trade_count"]
            if t10["realized_pnl_gbp"] <= 0 or t50["realized_pnl_gbp"] <= 0:
                row["ok"] = False
            print(
                f"  {days}d  top10 £{t10['realized_pnl_gbp']:+.2f} (n={t10['trade_count']})  "
                f"top50 £{t50['realized_pnl_gbp']:+.2f} (n={t50['trade_count']})",
                flush=True,
            )
        rows.append(row)

    winners = [r for r in rows if r["ok"]]
    # Prefer more trades on top50 60d, then higher min pnl across all 6 cells
    def score(r):
        pnls = [r[f"t10_{d}"] for d in windows] + [r[f"t50_{d}"] for d in windows]
        return (min(pnls), sum(pnls), r["t50_60_n"])

    winners.sort(key=score, reverse=True)
    out = {
        "goal": "single static formula, green on top10£20k AND top50£100k for 60/90/120d",
        "winners": winners,
        "all": rows,
        "pick": winners[0]["name"] if winners else None,
    }
    path = Path("artifacts/ab_golden_unify.json")
    path.write_text(json.dumps(out, indent=2))
    print("\n" + "=" * 72)
    if winners:
        print(f"PICK {winners[0]['name']}")
        for d in windows:
            print(
                f"  {d}d top10={winners[0][f't10_{d}']} top50={winners[0][f't50_{d}']}"
            )
    else:
        print("NO dual-green pack — need another round")
    print(f"Wrote {path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
