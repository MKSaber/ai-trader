#!/usr/bin/env python3
"""Historical paper backtest for candle pattern detector.

Fetches delayed Yahoo bars for top LSE symbols, detects patterns-v1
signals, and simulates long-only trades under a named trade-rules profile.

Usage (from candle-lab/backend with venv active):
  python scripts/backtest_20d.py --days 10 --rules trade-rules-v2 --broker trading212
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from curl_cffi import requests as curl_requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import BROKER_PROFILES, Settings, apply_broker_profile
from app.paper import (
    adverse_entry_price,
    adverse_exit_price,
    entry_costs,
    exit_costs,
    simulate_long_bar,
    size_shares,
)
from app.patterns import DETECTOR_VERSION, detect_closed_patterns, in_downtrend
from app.trade_rules import (
    TRADE_RULE_PROFILES,
    TradeRules,
    expected_net_at_target,
    load_trade_rules,
    setup_levels,
)

LONDON = ZoneInfo("Europe/London")


@dataclass
class OpenSetup:
    symbol: str
    pattern: str
    confirm_i: int
    confirm_ts: datetime
    entry_trigger: float
    stop: float
    target: float
    expiry_i: int
    status: str = "pending"
    qty: float = 0.0
    entry_price: float = 0.0
    entry_i: int | None = None
    exit_price: float = 0.0
    exit_i: int | None = None
    exit_reason: str = ""
    ambiguous: bool = False
    pnl_gbp: float = 0.0
    # patterns-v2 next-open confirmation
    pattern_close: float = 0.0
    awaiting_next_open: bool = False


@dataclass
class SimResult:
    symbol: str
    bars: int
    trading_days: int
    first_bar: str
    last_bar: str
    patterns: dict[str, int]
    trades: list[dict] = field(default_factory=list)
    starting_cash: float = 0.0
    ending_cash: float = 0.0
    realized_pnl: float = 0.0
    win_count: int = 0
    loss_count: int = 0
    expired_setups: int = 0


def _session():
    return curl_requests.Session(impersonate="chrome")


def fetch_bars(symbol: str, interval: str = "5m", period: str = "60d") -> pd.DataFrame:
    """Fetch Yahoo OHLCV bars (delayed/unofficial)."""
    print(f"  fetching {symbol} ({interval}) ...", flush=True)
    ticker = yf.Ticker(symbol, session=_session())
    frame = ticker.history(
        period=period,
        interval=interval,
        auto_adjust=False,
        prepost=False,
        actions=False,
    )
    if frame is None or frame.empty:
        print(f"  {symbol}: empty", flush=True)
        return pd.DataFrame()
    df = frame.reset_index()
    ts_col = "Datetime" if "Datetime" in df.columns else df.columns[0]
    df = df.rename(
        columns={
            ts_col: "bar_start",
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
    print(f"  {symbol}: {len(df)} bars", flush=True)
    return df.reset_index(drop=True)


# Back-compat alias used by hillclimb helpers
def fetch_5m(symbol: str, period: str = "60d") -> pd.DataFrame:
    return fetch_bars(symbol, interval="5m", period=period)


def filter_last_n_trading_days(df: pd.DataFrame, days: int) -> pd.DataFrame:
    if df.empty:
        return df
    local = df["bar_start"].dt.tz_convert(LONDON)
    trading_dates = sorted(local.dt.date.unique())
    keep = set(trading_dates[-days:])
    mask = local.dt.date.isin(keep)
    return df.loc[mask].reset_index(drop=True)


def _force_session_flat(bar_start: datetime) -> bool:
    local = bar_start.astimezone(LONDON)
    return local.hour > 16 or (local.hour == 16 and local.minute >= 20)


def _close_long(
    setup: OpenSetup,
    exit_mid: float,
    reason: str,
    ambiguous: bool,
    exit_i: int,
    cash: float,
    settings: Settings,
) -> tuple[OpenSetup, float, float]:
    fill_px = adverse_exit_price(exit_mid, settings)
    notional = setup.qty * fill_px
    costs = exit_costs(notional, settings)
    entry_notional = setup.qty * setup.entry_price
    entry_c = entry_costs(entry_notional, settings)
    pnl = (notional - costs.total) - (entry_notional + entry_c.total)
    cash += notional - costs.total
    setup.status = "closed_ambiguous" if ambiguous else "closed"
    setup.exit_price = fill_px
    setup.exit_i = exit_i
    setup.exit_reason = reason
    setup.ambiguous = ambiguous
    setup.pnl_gbp = pnl
    return setup, cash, pnl


def _trade_dict(s: OpenSetup) -> dict:
    return {
        "symbol": s.symbol,
        "pattern": s.pattern,
        "confirm_ts": s.confirm_ts.isoformat(),
        "entry_trigger": s.entry_trigger,
        "stop": s.stop,
        "target": s.target,
        "status": s.status,
        "qty": s.qty,
        "entry_price": s.entry_price,
        "exit_price": s.exit_price,
        "exit_reason": s.exit_reason,
        "ambiguous": s.ambiguous,
        "pnl_gbp": round(s.pnl_gbp, 4),
    }


def simulate_symbol(
    symbol: str,
    df: pd.DataFrame,
    settings: Settings,
    cash: float,
    rules: TradeRules,
) -> tuple[SimResult, float]:
    """Detect once, then chronologically replay entries/exits (no look-ahead fills)."""
    print(f"  detecting patterns on {symbol} ({len(df)} bars) ...", flush=True)
    dets = detect_closed_patterns(df)
    by_confirm: dict[int, list] = {}
    patterns_count: dict[str, int] = {}
    for det in dets:
        by_confirm.setdefault(det.confirm_index, []).append(det)
        patterns_count[det.pattern] = patterns_count.get(det.pattern, 0) + 1
    print(f"  {symbol}: {patterns_count or 'no patterns'}", flush=True)

    trades: list[dict] = []
    expired = 0
    open_setup: OpenSetup | None = None
    starting = cash
    realized = 0.0
    wins = 0
    losses = 0
    day_trade_counts: dict = {}
    local_dates = df["bar_start"].dt.tz_convert(LONDON).dt.date.unique()
    bullish = rules.bullish_set

    for i in range(len(df)):
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

        for det in by_confirm.get(i, []):
            if (
                rules.exit_on_bearish
                and det.direction == "down"
                and open_setup
                and open_setup.status == "open"
            ):
                open_setup, cash, pnl = _close_long(
                    open_setup,
                    close,
                    f"bearish_{det.pattern}",
                    False,
                    i,
                    cash,
                    settings,
                )
                realized += pnl
                wins += 1 if pnl >= 0 else 0
                losses += 1 if pnl < 0 else 0
                trades.append(_trade_dict(open_setup))
                open_setup = None

            if (
                det.direction == "up"
                and det.pattern in bullish
                and open_setup is None
            ):
                if (
                    rules.trade_hours_london is not None
                    and local.hour not in rules.trade_hours_london
                ):
                    continue
                if (
                    rules.max_trades_per_day is not None
                    and day_trade_counts.get(day, 0) >= rules.max_trades_per_day
                ):
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
                open_setup = OpenSetup(
                    symbol=symbol,
                    pattern=det.pattern,
                    confirm_i=i,
                    confirm_ts=bar_start,
                    entry_trigger=entry,
                    stop=stop,
                    target=target,
                    expiry_i=i + rules.setup_expiry_bars,
                )

        if open_setup is None:
            continue

        if open_setup.status == "pending":
            if i <= open_setup.confirm_i:
                continue
            if i > open_setup.expiry_i:
                open_setup.status = "expired"
                expired += 1
                open_setup = None
                continue
            if high >= open_setup.entry_trigger:
                mid = max(open_setup.entry_trigger, open_px)
                fill_px = adverse_entry_price(mid, settings)
                qty = size_shares(cash, fill_px, open_setup.stop, settings)
                if qty <= 0:
                    open_setup.status = "expired"
                    expired += 1
                    open_setup = None
                    continue
                notional = qty * fill_px
                ec = entry_costs(notional, settings)
                xc = exit_costs(qty * open_setup.target, settings)
                if rules.cost_gate:
                    net = expected_net_at_target(
                        qty,
                        fill_px,
                        open_setup.stop,
                        open_setup.target,
                        rules.reward_risk,
                        ec.total,
                        xc.total,
                    )
                    if net <= 0:
                        open_setup.status = "expired"
                        expired += 1
                        open_setup = None
                        continue
                cash -= notional + ec.total
                open_setup.status = "open"
                open_setup.qty = qty
                open_setup.entry_price = fill_px
                open_setup.entry_i = i
                day_trade_counts[day] = day_trade_counts.get(day, 0) + 1

        elif open_setup.status == "open":
            if open_setup.entry_i is not None and i == open_setup.entry_i:
                continue
            sim = simulate_long_bar(
                open_setup.entry_price,
                open_setup.stop,
                open_setup.target,
                high,
                low,
                close,
            )
            force = rules.session_flat and _force_session_flat(bar_start)
            if sim is None and not force:
                continue
            if sim is None:
                exit_mid, reason, ambiguous = close, "session_flat", False
            else:
                exit_mid, reason, ambiguous = sim.exit_mid, sim.reason, sim.ambiguous
            open_setup, cash, pnl = _close_long(
                open_setup, exit_mid, reason, ambiguous, i, cash, settings
            )
            realized += pnl
            wins += 1 if pnl >= 0 else 0
            losses += 1 if pnl < 0 else 0
            trades.append(_trade_dict(open_setup))
            open_setup = None

    if open_setup and open_setup.status == "open":
        row = df.iloc[-1]
        open_setup, cash, pnl = _close_long(
            open_setup,
            float(row["close"]),
            "end_of_series",
            False,
            len(df) - 1,
            cash,
            settings,
        )
        realized += pnl
        wins += 1 if pnl >= 0 else 0
        losses += 1 if pnl < 0 else 0
        trades.append(_trade_dict(open_setup))
    elif open_setup and open_setup.status == "pending":
        expired += 1

    result = SimResult(
        symbol=symbol,
        bars=len(df),
        trading_days=len(local_dates),
        first_bar=str(df["bar_start"].iloc[0]) if len(df) else "",
        last_bar=str(df["bar_start"].iloc[-1]) if len(df) else "",
        patterns=patterns_count,
        trades=trades,
        starting_cash=starting,
        ending_cash=cash,
        realized_pnl=realized,
        win_count=wins,
        loss_count=losses,
        expired_setups=expired,
    )
    return result, cash


def run(
    days: int,
    symbols: list[str],
    starting_cash: float,
    broker: str = "trading212",
    rules_version: str = "trade-rules-v2",
    interval: str | None = None,
) -> dict:
    settings = apply_broker_profile(
        Settings(starting_cash_gbp=starting_cash),
        broker,
    )
    rules = load_trade_rules(rules_version)
    settings = settings.model_copy(
        update={
            "trade_rules_version": rules.version,
            "reward_risk": rules.reward_risk,
            "setup_expiry_bars": rules.setup_expiry_bars,
        }
    )
    bar_interval = interval or rules.interval
    per_symbol: list[dict] = []
    all_trades: list[dict] = []
    pattern_totals: dict[str, int] = {}
    feed_notes: list[dict] = []
    profile_meta = BROKER_PROFILES[broker]

    for symbol in symbols:
        print(f"\n=== {symbol} ===", flush=True)
        raw = fetch_bars(symbol, interval=bar_interval, period="60d")
        if raw.empty:
            feed_notes.append({"symbol": symbol, "healthy": False, "message": "empty"})
            per_symbol.append(
                {
                    "symbol": symbol,
                    "error": "no_data",
                    "patterns": {},
                    "trades": [],
                    "realized_pnl": 0.0,
                }
            )
            continue
        df = filter_last_n_trading_days(raw, days)
        feed_notes.append(
            {
                "symbol": symbol,
                "healthy": True,
                "interval": bar_interval,
                "raw_bars": len(raw),
                "filtered_bars": len(df),
                "trading_days": int(
                    df["bar_start"].dt.tz_convert(LONDON).dt.date.nunique()
                )
                if len(df)
                else 0,
                "first": str(df["bar_start"].iloc[0]) if len(df) else None,
                "last": str(df["bar_start"].iloc[-1]) if len(df) else None,
                "message": "DELAYED Yahoo Finance via yfinance — not real-time.",
            }
        )
        if len(df) < 10:
            per_symbol.append(
                {
                    "symbol": symbol,
                    "error": "insufficient_bars",
                    "patterns": {},
                    "trades": [],
                    "realized_pnl": 0.0,
                }
            )
            continue
        result, _ = simulate_symbol(symbol, df, settings, starting_cash, rules)
        for k, v in result.patterns.items():
            pattern_totals[k] = pattern_totals.get(k, 0) + v
        all_trades.extend(result.trades)
        per_symbol.append(asdict(result))

    total_pnl = sum(t["pnl_gbp"] for t in all_trades)
    wins = sum(1 for t in all_trades if t["pnl_gbp"] >= 0)
    losses = sum(1 for t in all_trades if t["pnl_gbp"] < 0)
    n_trades = len(all_trades)
    ran = [s for s in per_symbol if s.get("bars")]
    portfolio_start = starting_cash * max(len(ran), 1)
    portfolio_end = (
        sum(s.get("ending_cash", starting_cash) for s in ran) if ran else starting_cash
    )
    portfolio_return_pct = (
        100.0 * (portfolio_end - portfolio_start) / portfolio_start if portfolio_start else 0.0
    )
    all_symbols_positive = all(
        float(s.get("realized_pnl") or 0) > 0 for s in ran
    ) and len(ran) == len(symbols)

    return {
        "detector_version": DETECTOR_VERSION,
        "trade_rules_version": rules.version,
        "trade_rules_label": rules.label,
        "interval": bar_interval,
        "cost_profile": broker,
        "cost_profile_label": profile_meta["label"],
        "costs": {
            "commission_bps": settings.commission_bps,
            "spread_bps": settings.spread_bps,
            "slippage_bps": settings.slippage_bps,
            "stamp_duty_rate": settings.stamp_duty_rate,
            "fx_bps": settings.fx_bps,
            "flat_commission_gbp": settings.flat_commission_gbp,
            "ptm_levy_gbp": settings.ptm_levy_gbp,
            "ptm_threshold_gbp": settings.ptm_threshold_gbp,
            "sources": "candle-lab/COST_SOURCES.md",
        },
        "days_requested": days,
        "symbols": symbols,
        "starting_cash_gbp_per_symbol": starting_cash,
        "feed": feed_notes,
        "pattern_totals": pattern_totals,
        "trade_count": n_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / n_trades) if n_trades else None,
        "total_realized_pnl_gbp": round(total_pnl, 4),
        "portfolio_start_gbp": round(portfolio_start, 2),
        "portfolio_end_gbp": round(portfolio_end, 2),
        "portfolio_return_pct": round(portfolio_return_pct, 4),
        "profitable": total_pnl > 0,
        "all_symbols_positive": all_symbols_positive,
        "per_symbol": per_symbol,
        "disclaimer": (
            "Paper simulation on DELAYED Yahoo bars. Broker/tax costs follow "
            "COST_SOURCES.md (GOV.UK SDRT, Takeover Panel PTM, T212/eToro schedules). "
            "Spread/slippage are market-friction assumptions. Not live execution proof. "
            "trade-rules-v2 was fit on this 10d window — treat as research, not proven edge."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Candle pattern paper backtest")
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument(
        "--symbols",
        default="VOD.L,BP.L,HSBA.L,GSK.L,AZN.L",
        help="Comma-separated Yahoo LSE tickers",
    )
    parser.add_argument("--cash", type=float, default=100_000.0)
    parser.add_argument(
        "--broker",
        default="trading212",
        choices=sorted(BROKER_PROFILES),
        help="Cost profile from COST_SOURCES.md",
    )
    parser.add_argument(
        "--rules",
        default="trade-rules-v2",
        choices=sorted(TRADE_RULE_PROFILES),
        help="Trade rule profile",
    )
    parser.add_argument(
        "--interval",
        default="",
        help="Override bar interval (default: from trade rules)",
    )
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    report = run(
        args.days,
        symbols,
        args.cash,
        broker=args.broker,
        rules_version=args.rules,
        interval=args.interval or None,
    )

    tag = f"{args.days}d_{args.rules}_{args.broker}".replace("trade-rules-", "rules")
    out_path = (
        Path(args.out)
        if args.out
        else Path("artifacts") / f"backtest_{tag}_report.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str))

    compact = {k: v for k, v in report.items() if k != "per_symbol"}
    compact["exit_reason_counts"] = dict(
        Counter(
            t["exit_reason"]
            for s in report["per_symbol"]
            for t in s.get("trades") or []
        )
    )
    compact["per_symbol"] = [
        {
            "symbol": s.get("symbol"),
            "trading_days": s.get("trading_days"),
            "bars": s.get("bars"),
            "patterns": s.get("patterns"),
            "trade_count": len(s.get("trades") or []),
            "realized_pnl": round(float(s.get("realized_pnl") or 0), 2),
            "wins": s.get("win_count"),
            "losses": s.get("loss_count"),
            "expired_setups": s.get("expired_setups"),
            "sample_trades": (s.get("trades") or [])[:3],
        }
        for s in report["per_symbol"]
    ]
    summary_path = out_path.with_name(
        out_path.name.replace("_report.json", "_summary.json")
        if out_path.name.endswith("_report.json")
        else f"{out_path.stem}_summary.json"
    )
    summary_path.write_text(json.dumps(compact, indent=2, default=str))

    print("=" * 72)
    print(f"Candle pattern detector — last {args.days} trading days paper backtest")
    print("=" * 72)
    print(f"Symbols: {', '.join(symbols)}")
    print(
        f"Detector: {report['detector_version']} | Rules: {report['trade_rules_version']} "
        f"({report['interval']})"
    )
    print(f"  {report['trade_rules_label']}")
    print(f"Costs: {report['cost_profile']} — {report['cost_profile_label']}")
    print(f"Patterns detected: {report['pattern_totals'] or '(none)'}")
    print(f"Trades: {report['trade_count']}  wins={report['wins']}  losses={report['losses']}")
    wr = report["win_rate"]
    print(f"Win rate: {wr:.1%}" if wr is not None else "Win rate: n/a")
    print(f"Total realized P&L: £{report['total_realized_pnl_gbp']:,.2f}")
    print(
        f"Portfolio: £{report['portfolio_start_gbp']:,.0f} → "
        f"£{report['portfolio_end_gbp']:,.0f} "
        f"({report['portfolio_return_pct']:+.3f}%)"
    )
    print(f"Profitable: {report['profitable']}")
    print(f"All 5 symbols positive: {report['all_symbols_positive']}")
    print(f"Exit reasons: {compact['exit_reason_counts']}")
    print("-" * 72)
    for s in report["per_symbol"]:
        if s.get("error"):
            print(f"  {s['symbol']}: ERROR {s['error']}")
            continue
        print(
            f"  {s['symbol']}: days={s['trading_days']} bars={s['bars']} "
            f"patterns={s['patterns']} trades={len(s['trades'])} "
            f"pnl=£{s['realized_pnl']:,.2f}"
        )
        for t in s["trades"][:8]:
            print(
                f"      {t['pattern']} entry={t['entry_price']:.4f} "
                f"exit={t['exit_price']:.4f} ({t['exit_reason']}) "
                f"pnl=£{t['pnl_gbp']:,.2f}"
            )
        if len(s["trades"]) > 8:
            print(f"      ... {len(s['trades']) - 8} more trades")
    print("-" * 72)
    print(report["disclaimer"])
    print(f"Wrote {out_path.resolve()}")
    print(f"Wrote {summary_path.resolve()}")
    return 0 if report["all_symbols_positive"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
