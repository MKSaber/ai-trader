#!/usr/bin/env python3
"""20-day historical paper backtest for candle pattern detector.

Fetches delayed Yahoo 5m bars for top LSE symbols, detects patterns-v1
signals, and simulates long-only buy/sell vs trade-rules-v1 insights.

Usage (from candle-lab/backend with venv active):
  python scripts/backtest_20d.py
  python scripts/backtest_20d.py --days 20 --symbols VOD.L,BP.L,HSBA.L,GSK.L,AZN.L
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

from app.config import Settings
from app.paper import (
    adverse_entry_price,
    adverse_exit_price,
    entry_costs,
    exit_costs,
    simulate_long_bar,
    size_shares,
)
from app.patterns import DETECTOR_VERSION, detect_closed_patterns

LONDON = ZoneInfo("Europe/London")
BULLISH_TRADE_PATTERNS = {"bullish_engulfing", "hammer"}


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


def fetch_5m(symbol: str, period: str = "60d") -> pd.DataFrame:
    """Fetch up to ~60d of 5m Yahoo bars (delayed/unofficial)."""
    print(f"  fetching {symbol} ...", flush=True)
    ticker = yf.Ticker(symbol, session=_session())
    frame = ticker.history(
        period=period,
        interval="5m",
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


def simulate_symbol(
    symbol: str,
    df: pd.DataFrame,
    settings: Settings,
    cash: float,
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
    local_dates = df["bar_start"].dt.tz_convert(LONDON).dt.date.unique()

    for i in range(len(df)):
        row = df.iloc[i]
        bar_start = pd.Timestamp(row["bar_start"]).to_pydatetime()
        if bar_start.tzinfo is None:
            bar_start = bar_start.replace(tzinfo=timezone.utc)
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        open_px = float(row["open"])

        # Insights confirmed on this closed bar
        for det in by_confirm.get(i, []):
            if det.direction == "down" and open_setup and open_setup.status == "open":
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
                and det.pattern in BULLISH_TRADE_PATTERNS
                and open_setup is None
            ):
                entry = high * (1.0 + settings.entry_buffer_frac)
                stop = low * (1.0 - settings.stop_buffer_frac)
                risk = max(entry - stop, entry * 1e-4)
                target = entry + settings.reward_risk * risk
                open_setup = OpenSetup(
                    symbol=symbol,
                    pattern=det.pattern,
                    confirm_i=i,
                    confirm_ts=bar_start,
                    entry_trigger=entry,
                    stop=stop,
                    target=target,
                    expiry_i=i + settings.setup_expiry_bars,
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
                costs = entry_costs(notional, settings)
                cash -= notional + costs.total
                open_setup.status = "open"
                open_setup.qty = qty
                open_setup.entry_price = fill_px
                open_setup.entry_i = i

        elif open_setup.status == "open":
            # Don't exit on the same bar as entry
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
            force = _force_session_flat(bar_start)
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


def run(days: int, symbols: list[str], starting_cash: float) -> dict:
    settings = Settings(starting_cash_gbp=starting_cash)
    per_symbol: list[dict] = []
    all_trades: list[dict] = []
    pattern_totals: dict[str, int] = {}
    feed_notes: list[dict] = []

    for symbol in symbols:
        print(f"\n=== {symbol} ===", flush=True)
        raw = fetch_5m(symbol, period="60d")
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
        result, _ = simulate_symbol(symbol, df, settings, starting_cash)
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

    return {
        "detector_version": DETECTOR_VERSION,
        "trade_rules_version": settings.trade_rules_version,
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
        "per_symbol": per_symbol,
        "disclaimer": (
            "Paper simulation on DELAYED Yahoo 5m bars. Costs include spread, "
            "slippage, commission, and UK stamp duty on buys. Not live execution proof."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="20d candle pattern paper backtest")
    parser.add_argument("--days", type=int, default=20)
    parser.add_argument(
        "--symbols",
        default="VOD.L,BP.L,HSBA.L,GSK.L,AZN.L",
        help="Comma-separated Yahoo LSE tickers",
    )
    parser.add_argument("--cash", type=float, default=100_000.0)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    report = run(args.days, symbols, args.cash)

    out_path = Path(args.out) if args.out else Path("artifacts") / "backtest_20d_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str))

    # Compact summary (no full trade lists) for quick review
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
    summary_path = out_path.with_name("backtest_20d_summary.json")
    summary_path.write_text(json.dumps(compact, indent=2, default=str))

    print("=" * 72)
    print(f"Candle pattern detector — last {args.days} trading days paper backtest")
    print("=" * 72)
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Detector: {report['detector_version']} | Rules: {report['trade_rules_version']}")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
