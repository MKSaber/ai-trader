"""Session runner: poll delayed feed, detect patterns, manage paper longs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import (
    CandleBar,
    Experiment,
    LedgerSnapshot,
    PaperFill,
    PatternSignal,
    SessionRun,
    Setup,
)
from app.paper import (
    adverse_entry_price,
    adverse_exit_price,
    entry_costs,
    exit_costs,
    simulate_long_bar,
    size_shares,
    utcnow,
)
from app.patterns import DETECTOR_VERSION, detect_closed_patterns
from app.provider import fetch_intraday_5m, london_today

LONDON = ZoneInfo("Europe/London")


def freeze_experiment(db: Session) -> Experiment:
    s = get_settings()
    exp = Experiment(
        name=f"candle-{london_today().isoformat()}",
        detector_version=s.detector_version,
        trade_rules_version=s.trade_rules_version,
        config_json=json.dumps(s.model_dump()),
        created_at=utcnow(),
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)
    return exp


def start_session(db: Session, experiment_id: int) -> SessionRun:
    s = get_settings()
    run = SessionRun(
        experiment_id=experiment_id,
        session_date=london_today().isoformat(),
        status="running",
        feed_label=s.feed_label,
        feed_is_realtime=s.feed_is_realtime,
        started_at=utcnow(),
        notes=(
            "DELAYED Yahoo observation experiment — not real-time execution proof."
        ),
    )
    db.add(run)
    db.flush()
    db.add(
        LedgerSnapshot(
            session_run_id=run.id,
            as_of=utcnow(),
            cash_gbp=s.starting_cash_gbp,
            equity_gbp=s.starting_cash_gbp,
            exposure_gbp=0.0,
            notes="session start",
        )
    )
    db.commit()
    db.refresh(run)
    return run


def _upsert_bars(db: Session, symbol: str, df: pd.DataFrame) -> int:
    s = get_settings()
    n = 0
    arrival = utcnow()
    for _, row in df.iterrows():
        bar_start = pd.Timestamp(row["bar_start"]).to_pydatetime()
        if bar_start.tzinfo is None:
            bar_start = bar_start.replace(tzinfo=timezone.utc)
        existing = db.scalar(
            select(CandleBar).where(
                CandleBar.symbol == symbol,
                CandleBar.bar_start == bar_start,
                CandleBar.interval_minutes == s.interval_minutes,
            )
        )
        if existing:
            existing.high = max(existing.high, float(row["high"]))
            existing.low = min(existing.low, float(row["low"]))
            existing.close = float(row["close"])
            existing.volume = float(row["volume"])
            existing.closed = bool(row["closed"])
            existing.arrival_ts = arrival
        else:
            db.add(
                CandleBar(
                    symbol=symbol,
                    interval_minutes=s.interval_minutes,
                    bar_start=bar_start,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    closed=bool(row["closed"]),
                    event_ts=bar_start,
                    arrival_ts=arrival,
                )
            )
            n += 1
    db.commit()
    return n


def _bars_frame(db: Session, symbol: str) -> pd.DataFrame:
    s = get_settings()
    rows = db.scalars(
        select(CandleBar)
        .where(
            CandleBar.symbol == symbol,
            CandleBar.interval_minutes == s.interval_minutes,
        )
        .order_by(CandleBar.bar_start)
    ).all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "bar_start": r.bar_start,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "closed": r.closed,
            }
            for r in rows
        ]
    )


def _issue_signal(
    db: Session,
    run_id: int,
    symbol: str,
    pattern: str,
    direction: str,
    confirm_bar_start: datetime,
    bars_slice: pd.DataFrame,
    conditions: dict,
) -> PatternSignal | None:
    s = get_settings()
    exists = db.scalar(
        select(PatternSignal).where(
            PatternSignal.symbol == symbol,
            PatternSignal.pattern == pattern,
            PatternSignal.confirm_bar_start == confirm_bar_start,
            PatternSignal.detector_version == s.detector_version,
        )
    )
    if exists:
        return None
    sig = PatternSignal(
        session_run_id=run_id,
        symbol=symbol,
        pattern=pattern,
        direction=direction,
        confirm_bar_start=confirm_bar_start,
        issued_at=utcnow(),
        detector_version=s.detector_version,
        bars_json=bars_slice.to_json(orient="records", date_format="iso"),
        conditions_json=json.dumps(conditions),
        provisional=False,
    )
    db.add(sig)
    db.flush()
    return sig


def _create_long_setup(
    db: Session, run_id: int, sig: PatternSignal, pattern_high: float, pattern_low: float
) -> Setup | None:
    s = get_settings()
    open_pos = db.scalar(
        select(Setup).where(
            Setup.session_run_id == run_id,
            Setup.symbol == sig.symbol,
            Setup.status.in_(["pending", "open"]),
        )
    )
    if open_pos:
        return None
    entry = pattern_high * (1.0 + s.entry_buffer_frac)
    stop = pattern_low * (1.0 - s.stop_buffer_frac)
    risk = max(entry - stop, entry * 1e-4)
    target = entry + s.reward_risk * risk
    expiry = sig.confirm_bar_start + timedelta(minutes=s.interval_minutes * s.setup_expiry_bars)
    setup = Setup(
        signal_id=sig.id,
        session_run_id=run_id,
        symbol=sig.symbol,
        side="long",
        status="pending",
        entry_trigger=entry,
        stop=stop,
        target=target,
        expiry_bar_start=expiry,
        rules_version=s.trade_rules_version,
        created_at=utcnow(),
    )
    db.add(setup)
    db.flush()
    return setup


def _ledger_cash(db: Session, run_id: int) -> float:
    snap = db.scalars(
        select(LedgerSnapshot)
        .where(LedgerSnapshot.session_run_id == run_id)
        .order_by(LedgerSnapshot.id.desc())
    ).first()
    s = get_settings()
    return snap.cash_gbp if snap else s.starting_cash_gbp


def _process_setups(db: Session, run_id: int, symbol: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    s = get_settings()
    closed = df[df["closed"]].copy()
    if closed.empty:
        return
    last = closed.iloc[-1]
    bar_start = pd.Timestamp(last["bar_start"]).to_pydatetime()
    setups = db.scalars(
        select(Setup).where(
            Setup.session_run_id == run_id,
            Setup.symbol == symbol,
            Setup.status.in_(["pending", "open"]),
        )
    ).all()
    cash = _ledger_cash(db, run_id)
    for setup in setups:
        if setup.status == "pending":
            if bar_start >= setup.expiry_bar_start:
                setup.status = "expired"
                continue
            # Arrival-time fill: use current closed bar only (no lookback fill)
            if float(last["high"]) >= setup.entry_trigger:
                mid = max(setup.entry_trigger, float(last["open"]))
                fill_px = adverse_entry_price(mid)
                qty = size_shares(cash, fill_px, setup.stop)
                if qty <= 0:
                    setup.status = "excluded_no_cash"
                    continue
                notional = qty * fill_px
                costs = entry_costs(notional)
                cash -= notional + costs.total
                db.add(
                    PaperFill(
                        setup_id=setup.id,
                        kind="entry",
                        fill_ts=utcnow(),
                        price=fill_px,
                        qty=qty,
                        reason="entry_touch_arrival_bar",
                        ambiguous=False,
                    )
                )
                setup.status = "open"
                db.add(
                    LedgerSnapshot(
                        session_run_id=run_id,
                        as_of=utcnow(),
                        cash_gbp=cash,
                        equity_gbp=cash + notional,
                        exposure_gbp=notional,
                        notes=f"entry {symbol}",
                    )
                )
        elif setup.status == "open":
            entry_fill = db.scalar(
                select(PaperFill).where(
                    PaperFill.setup_id == setup.id, PaperFill.kind == "entry"
                )
            )
            if not entry_fill:
                continue
            sim = simulate_long_bar(
                entry_fill.price,
                setup.stop,
                setup.target,
                float(last["high"]),
                float(last["low"]),
                float(last["close"]),
            )
            # Force flat near session end (London 16:30)
            local = bar_start.astimezone(LONDON)
            force_close = local.hour > 16 or (local.hour == 16 and local.minute >= 20)
            if sim is None and not force_close:
                continue
            if sim is None:
                exit_mid = float(last["close"])
                reason = "session_flat"
                ambiguous = False
            else:
                exit_mid = sim.exit_mid
                reason = sim.reason
                ambiguous = sim.ambiguous
            fill_px = adverse_exit_price(exit_mid)
            notional = entry_fill.qty * fill_px
            costs = exit_costs(entry_fill.qty * fill_px)
            cash = _ledger_cash(db, run_id) + notional - costs.total
            db.add(
                PaperFill(
                    setup_id=setup.id,
                    kind="exit",
                    fill_ts=utcnow(),
                    price=fill_px,
                    qty=entry_fill.qty,
                    reason=reason,
                    ambiguous=ambiguous,
                )
            )
            setup.status = "closed_ambiguous" if ambiguous else "closed"
            db.add(
                LedgerSnapshot(
                    session_run_id=run_id,
                    as_of=utcnow(),
                    cash_gbp=cash,
                    equity_gbp=cash,
                    exposure_gbp=0.0,
                    notes=f"exit {symbol} {reason}",
                )
            )
    db.commit()


def poll_once(db: Session, run_id: int) -> dict:
    """One poll cycle for all symbols."""
    s = get_settings()
    run = db.get(SessionRun, run_id)
    if not run or run.status != "running":
        return {"ok": False, "message": "no running session"}
    feed_msgs = []
    detections = 0
    for symbol in s.symbol_list:
        df, status = fetch_intraday_5m(symbol, period="5d")
        feed_msgs.append({"symbol": symbol, **status.__dict__})
        if df.empty or not status.healthy:
            continue
        _upsert_bars(db, symbol, df)
        frame = _bars_frame(db, symbol)
        closed = frame[frame["closed"]].copy()
        if len(closed) < 8:
            continue
        found = detect_closed_patterns(closed)
        for det in found:
            # Only emit if confirm bar is among the newest few (avoid replay spam on first poll)
            confirm_i = det.confirm_index
            confirm_ts = pd.Timestamp(closed.iloc[confirm_i]["bar_start"]).to_pydatetime()
            if confirm_ts.tzinfo is None:
                confirm_ts = confirm_ts.replace(tzinfo=timezone.utc)
            # Limit to last 3 closed bars for live issuance
            if confirm_i < len(closed) - 3:
                continue
            slice_df = closed.iloc[max(0, confirm_i - 2) : confirm_i + 1]
            sig = _issue_signal(
                db,
                run_id,
                symbol,
                det.pattern,
                det.direction,
                confirm_ts,
                slice_df,
                det.conditions,
            )
            if not sig:
                continue
            detections += 1
            if det.direction == "up" and det.pattern in {
                "bullish_engulfing",
                "hammer",
            }:
                row = closed.iloc[confirm_i]
                _create_long_setup(
                    db, run_id, sig, float(row["high"]), float(row["low"])
                )
            # Bearish: observation only (no short); may mark exit intent
            if det.direction == "down":
                open_long = db.scalar(
                    select(Setup).where(
                        Setup.session_run_id == run_id,
                        Setup.symbol == symbol,
                        Setup.status == "open",
                    )
                )
                if open_long:
                    # Soft flag via note on next ledger — exit handled by stop/target/EOD
                    pass
        db.commit()
        _process_setups(db, run_id, symbol, frame)
    return {
        "ok": True,
        "detections_issued": detections,
        "feed": [
            {
                "symbol": m["symbol"],
                "healthy": m["healthy"],
                "delay_seconds": m["delay_seconds"],
                "message": m["message"],
                "is_realtime": m["is_realtime"],
                "label": m["label"],
            }
            for m in feed_msgs
        ],
    }


def day_chart_payload(
    db: Session,
    symbol: str,
    day: str,
) -> dict:
    """Candles + patterns + setups for one London calendar day (learning view)."""
    s = get_settings()
    day_date = datetime.fromisoformat(day).date()
    start = datetime(day_date.year, day_date.month, day_date.day, tzinfo=LONDON)
    end = start + timedelta(days=1)
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)

    # Yahoo 5m history is typically ~60 days — use that for Learn (not 7d).
    df, status = fetch_intraday_5m(symbol, period="60d")
    if not df.empty:
        _upsert_bars(db, symbol, df)

    rows = db.scalars(
        select(CandleBar)
        .where(
            CandleBar.symbol == symbol,
            CandleBar.interval_minutes == s.interval_minutes,
            CandleBar.bar_start >= start_utc,
            CandleBar.bar_start < end_utc,
        )
        .order_by(CandleBar.bar_start)
    ).all()
    candles = [
        {
            "bar_start": r.bar_start.isoformat(),
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
            "closed": r.closed,
        }
        for r in rows
    ]

    # London calendar days that currently have bars (for empty-day hints)
    all_bars = db.scalars(
        select(CandleBar)
        .where(
            CandleBar.symbol == symbol,
            CandleBar.interval_minutes == s.interval_minutes,
        )
        .order_by(CandleBar.bar_start.desc())
        .limit(5000)
    ).all()
    available_days: list[str] = []
    seen: set[str] = set()
    for b in all_bars:
        local = b.bar_start.astimezone(LONDON).date().isoformat()
        if local not in seen:
            seen.add(local)
            available_days.append(local)
    available_days.sort(reverse=True)
    suggested_day = available_days[0] if available_days else None

    # Detect on closed bars for the day (+ prior warm-up from DB)
    frame = _bars_frame(db, symbol)
    closed = frame[frame["closed"]].copy() if not frame.empty else pd.DataFrame()
    patterns = []
    if not closed.empty:
        # warm-up: include bars before day for trend context, but only report day confirms
        dets = detect_closed_patterns(closed)
        for det in dets:
            ts = pd.Timestamp(closed.iloc[det.confirm_index]["bar_start"]).to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if not (start_utc <= ts < end_utc):
                continue
            row = closed.iloc[det.confirm_index]
            patterns.append(
                {
                    "pattern": det.pattern,
                    "direction": det.direction,
                    "confirm_bar_start": ts.isoformat(),
                    "conditions": det.conditions,
                    "pattern_high": float(row["high"]),
                    "pattern_low": float(row["low"]),
                    "entry_trigger": float(row["high"]) * (1.0 + s.entry_buffer_frac)
                    if det.direction == "up"
                    else None,
                    "stop": float(row["low"]) * (1.0 - s.stop_buffer_frac)
                    if det.direction == "up"
                    else None,
                    "take_profit": (
                        float(row["high"]) * (1.0 + s.entry_buffer_frac)
                        + s.reward_risk
                        * (
                            float(row["high"]) * (1.0 + s.entry_buffer_frac)
                            - float(row["low"]) * (1.0 - s.stop_buffer_frac)
                        )
                    )
                    if det.direction == "up"
                    else None,
                    "action": (
                        "buy_setup"
                        if det.direction == "up"
                        else "sell_observation_or_exit_long"
                    ),
                }
            )

    signals = db.scalars(
        select(PatternSignal).where(
            PatternSignal.symbol == symbol,
            PatternSignal.confirm_bar_start >= start_utc,
            PatternSignal.confirm_bar_start < end_utc,
        )
    ).all()
    setups = []
    for sig in signals:
        st = db.scalar(select(Setup).where(Setup.signal_id == sig.id))
        if not st:
            continue
        fills = db.scalars(select(PaperFill).where(PaperFill.setup_id == st.id)).all()
        setups.append(
            {
                "id": st.id,
                "pattern": sig.pattern,
                "status": st.status,
                "entry_trigger": st.entry_trigger,
                "stop": st.stop,
                "target": st.target,
                "expiry_bar_start": st.expiry_bar_start.isoformat(),
                "fills": [
                    {
                        "kind": f.kind,
                        "price": f.price,
                        "qty": f.qty,
                        "reason": f.reason,
                        "ambiguous": f.ambiguous,
                        "fill_ts": f.fill_ts.isoformat(),
                    }
                    for f in fills
                ],
            }
        )

    empty_reason = None
    if not candles:
        wd = day_date.weekday()
        if wd >= 5:
            empty_reason = "weekend_no_lse_session"
        elif suggested_day and day != suggested_day:
            empty_reason = "no_bars_for_day"
        else:
            empty_reason = "no_bars_in_feed"

    return {
        "symbol": symbol,
        "day": day,
        "timezone": "Europe/London",
        "feed": {
            "label": status.label,
            "is_realtime": False,
            "message": status.message,
            "delay_seconds": status.delay_seconds,
            "healthy": status.healthy,
        },
        "candles": candles,
        "patterns": patterns,
        "setups": setups,
        "available_days": available_days[:20],
        "suggested_day": suggested_day,
        "empty_reason": empty_reason,
        "detector_version": s.detector_version,
        "trade_rules_version": s.trade_rules_version,
        "note": (
            "Learning chart: patterns detected on closed 5m candles; "
            "buy/stop/take-profit levels follow trade-rules-v1 (illustrative). "
            "Pick a London session weekday — weekends have no LSE 5m bars."
        ),
    }
