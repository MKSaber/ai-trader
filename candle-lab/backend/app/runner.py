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
from app.patterns import (
    DETECTOR_VERSION,
    detect_closed_patterns,
    downtrend_depth_pct,
    in_downtrend,
)
from app.provider import fetch_intraday, london_today
from app.trade_rules import (
    load_trade_rules,
    passes_quality_filters,
    pattern_levels_from_detection,
    setup_levels,
    sync_settings_from_rules,
)

LONDON = ZoneInfo("Europe/London")


def _active_rules_and_settings():
    """Load frozen trade-rules profile and sync Settings knobs to match."""
    base = get_settings()
    rules = load_trade_rules(base.trade_rules_version)
    return rules, sync_settings_from_rules(base, rules)


def freeze_experiment(db: Session) -> Experiment:
    rules, s = _active_rules_and_settings()
    exp = Experiment(
        name=f"candle-{london_today().isoformat()}",
        detector_version=DETECTOR_VERSION,
        trade_rules_version=rules.version,
        config_json=json.dumps(s.model_dump()),
        created_at=utcnow(),
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)
    return exp


def start_session(db: Session, experiment_id: int) -> SessionRun:
    _rules, s = _active_rules_and_settings()
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
    _rules, s = _active_rules_and_settings()
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
    _rules, s = _active_rules_and_settings()
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
    exists = db.scalar(
        select(PatternSignal).where(
            PatternSignal.symbol == symbol,
            PatternSignal.pattern == pattern,
            PatternSignal.confirm_bar_start == confirm_bar_start,
            PatternSignal.detector_version == DETECTOR_VERSION,
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
        detector_version=DETECTOR_VERSION,
        bars_json=bars_slice.to_json(orient="records", date_format="iso"),
        conditions_json=json.dumps(conditions),
        provisional=False,
    )
    db.add(sig)
    db.flush()
    return sig


def _create_long_setup(
    db: Session,
    run_id: int,
    sig: PatternSignal,
    pattern_high: float,
    pattern_low: float,
    rules,
    settings,
) -> Setup | None:
    open_pos = db.scalar(
        select(Setup).where(
            Setup.session_run_id == run_id,
            Setup.symbol == sig.symbol,
            Setup.status.in_(["pending", "open"]),
        )
    )
    if open_pos:
        return None
    entry, stop, target = setup_levels(
        pattern_high,
        pattern_low,
        entry_buffer_frac=settings.entry_buffer_frac,
        stop_buffer_frac=settings.stop_buffer_frac,
        reward_risk=rules.reward_risk,
        stop_pad_ranges=rules.stop_pad_ranges,
    )
    expiry = sig.confirm_bar_start + timedelta(
        minutes=settings.interval_minutes * rules.setup_expiry_bars
    )
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
        rules_version=rules.version,
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
    _rules, s = _active_rules_and_settings()
    return snap.cash_gbp if snap else s.starting_cash_gbp


def _process_setups(db: Session, run_id: int, symbol: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    _rules, s = _active_rules_and_settings()
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
                fill_px = adverse_entry_price(mid, s)
                qty = size_shares(cash, fill_px, setup.stop, s)
                if qty <= 0:
                    setup.status = "excluded_no_cash"
                    continue
                notional = qty * fill_px
                costs = entry_costs(notional, s)
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
            fill_px = adverse_exit_price(exit_mid, s)
            notional = entry_fill.qty * fill_px
            costs = exit_costs(entry_fill.qty * fill_px, s)
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
    """One poll cycle for all symbols under the active trade-rules profile."""
    rules, s = _active_rules_and_settings()
    run = db.get(SessionRun, run_id)
    if not run or run.status != "running":
        return {"ok": False, "message": "no running session"}
    feed_msgs = []
    detections = 0
    # 60m history needs a longer Yahoo period than 5m
    period = "60d" if s.interval_minutes >= 60 else "5d"
    for symbol in s.symbol_list:
        if symbol in rules.blocklist_set:
            continue
        df, status = fetch_intraday(symbol, period=period, interval_minutes=s.interval_minutes)
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
            if det.direction == "up":
                row = closed.iloc[confirm_i]
                local = confirm_ts.astimezone(LONDON)
                if not passes_quality_filters(
                    rules=rules,
                    pattern=det.pattern,
                    conditions=det.conditions,
                    bar_high=float(row["high"]),
                    bar_low=float(row["low"]),
                    bar_close=float(row["close"]),
                    downtrend_ok=in_downtrend(closed, confirm_i),
                    downtrend_pct=downtrend_depth_pct(closed, confirm_i),
                    local_hour=local.hour,
                ):
                    continue
                ph, pl, _pc = pattern_levels_from_detection(
                    det.conditions,
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                )
                _create_long_setup(db, run_id, sig, ph, pl, rules, s)
            # Bearish: observation only (no short); exit handled by stop/target/EOD
        db.commit()
        _process_setups(db, run_id, symbol, frame)
    return {
        "ok": True,
        "detections_issued": detections,
        "trade_rules_version": rules.version,
        "interval_minutes": s.interval_minutes,
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
    rules, s = _active_rules_and_settings()
    day_date = datetime.fromisoformat(day).date()
    start = datetime(day_date.year, day_date.month, day_date.day, tzinfo=LONDON)
    end = start + timedelta(days=1)
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)

    # Yahoo intraday history is typically ~60 days — use that for Learn.
    period = "60d" if s.interval_minutes >= 60 else "60d"
    df, status = fetch_intraday(
        symbol, period=period, interval_minutes=s.interval_minutes
    )
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
            ph, pl, _pc = pattern_levels_from_detection(
                det.conditions,
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
            )
            entry = stop = tp = None
            action = "sell_observation_or_exit_long"
            if det.direction == "up":
                local = ts.astimezone(LONDON)
                ok = passes_quality_filters(
                    rules=rules,
                    pattern=det.pattern,
                    conditions=det.conditions,
                    bar_high=float(row["high"]),
                    bar_low=float(row["low"]),
                    bar_close=float(row["close"]),
                    downtrend_ok=in_downtrend(closed, det.confirm_index),
                    downtrend_pct=downtrend_depth_pct(closed, det.confirm_index),
                    local_hour=local.hour,
                )
                if ok:
                    entry, stop, tp = setup_levels(
                        ph,
                        pl,
                        entry_buffer_frac=s.entry_buffer_frac,
                        stop_buffer_frac=s.stop_buffer_frac,
                        reward_risk=rules.reward_risk,
                        stop_pad_ranges=rules.stop_pad_ranges,
                    )
                    action = "buy_setup"
                else:
                    action = "up_filtered_by_rules"
            patterns.append(
                {
                    "pattern": det.pattern,
                    "direction": det.direction,
                    "confirm_bar_start": ts.isoformat(),
                    "conditions": det.conditions,
                    "pattern_high": ph,
                    "pattern_low": pl,
                    "entry_trigger": entry,
                    "stop": stop,
                    "take_profit": tp,
                    "action": action,
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
        "detector_version": DETECTOR_VERSION,
        "trade_rules_version": rules.version,
        "interval_minutes": s.interval_minutes,
        "note": (
            f"Learning chart: patterns on closed {s.interval_minutes}m candles; "
            f"buy/stop/take-profit follow {rules.version} "
            f"({', '.join(rules.bullish_patterns)}, RR={rules.reward_risk}). "
            "Pick a London session weekday — weekends have no LSE bars."
        ),
    }
