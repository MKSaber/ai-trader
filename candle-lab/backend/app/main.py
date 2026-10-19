"""FastAPI entry for Live Candle Pattern Test (port 8100)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import (
    LedgerSnapshot,
    PatternSignal,
    SessionRun,
    Setup,
    get_db,
    init_db,
)
from app.patterns import DETECTOR_VERSION
from app.runner import day_chart_payload, freeze_experiment, poll_once, start_session
from app.trade_rules import load_trade_rules, sync_settings_from_rules


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Live Candle Pattern Test",
    version="0.1.0",
    lifespan=lifespan,
)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    base = get_settings()
    rules = load_trade_rules(base.trade_rules_version)
    s = sync_settings_from_rules(base, rules)
    return {
        "app": "Live Candle Pattern Test",
        "status": "ok",
        "detector_version": DETECTOR_VERSION,
        "trade_rules_version": rules.version,
        "trade_rules_label": rules.label,
        "bullish_patterns": list(rules.bullish_patterns),
        "interval_minutes": s.interval_minutes,
        "reward_risk": rules.reward_risk,
        "feed_label": s.feed_label,
        "feed_is_realtime": False,
        "disclaimer": (
            "Independent of LSE Pattern Lab. Feed is DELAYED Yahoo via yfinance. "
            "Paper trading only — no broker orders. Simulator uses trade-rules-v2.6."
        ),
        "symbols": s.symbol_list,
    }


@app.post("/api/session/start")
def session_start(db: Session = Depends(get_db)) -> dict[str, Any]:
    exp = freeze_experiment(db)
    run = start_session(db, exp.id)
    return {
        "experiment_id": exp.id,
        "session_run_id": run.id,
        "session_date": run.session_date,
        "feed_is_realtime": False,
        "feed_label": run.feed_label,
        "warning": run.notes,
    }


@app.post("/api/session/{run_id}/poll")
def session_poll(run_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return poll_once(db, run_id)


@app.get("/api/session/{run_id}")
def session_get(run_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = db.get(SessionRun, run_id)
    if not run:
        raise HTTPException(404, "session not found")
    signals = db.scalars(
        select(PatternSignal).where(PatternSignal.session_run_id == run_id)
    ).all()
    setups = db.scalars(select(Setup).where(Setup.session_run_id == run_id)).all()
    ledger = db.scalars(
        select(LedgerSnapshot)
        .where(LedgerSnapshot.session_run_id == run_id)
        .order_by(LedgerSnapshot.id.desc())
        .limit(20)
    ).all()
    return {
        "run": {
            "id": run.id,
            "session_date": run.session_date,
            "status": run.status,
            "feed_label": run.feed_label,
            "feed_is_realtime": run.feed_is_realtime,
            "notes": run.notes,
        },
        "signals": [
            {
                "id": s.id,
                "symbol": s.symbol,
                "pattern": s.pattern,
                "direction": s.direction,
                "confirm_bar_start": s.confirm_bar_start.isoformat(),
                "visual_review": s.visual_review,
                "detector_version": s.detector_version,
            }
            for s in signals
        ],
        "setups": [
            {
                "id": u.id,
                "symbol": u.symbol,
                "status": u.status,
                "entry_trigger": u.entry_trigger,
                "stop": u.stop,
                "target": u.target,
            }
            for u in setups
        ],
        "ledger": [
            {
                "as_of": x.as_of.isoformat(),
                "cash_gbp": x.cash_gbp,
                "equity_gbp": x.equity_gbp,
                "exposure_gbp": x.exposure_gbp,
                "notes": x.notes,
            }
            for x in ledger
        ],
    }


class ReviewBody(BaseModel):
    review: str  # confirmed | rejected | uncertain
    note: str | None = None


@app.post("/api/signals/{signal_id}/review")
def review_signal(
    signal_id: int, body: ReviewBody, db: Session = Depends(get_db)
) -> dict[str, Any]:
    if body.review not in {"confirmed", "rejected", "uncertain"}:
        raise HTTPException(400, "invalid review")
    sig = db.get(PatternSignal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    sig.visual_review = body.review
    sig.visual_note = body.note
    db.commit()
    return {"id": sig.id, "visual_review": sig.visual_review}


@app.get("/api/chart/day")
def chart_day(
    symbol: str,
    day: date | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Learning subtab: one symbol, one London day, patterns + levels."""
    s = get_settings()
    if symbol not in s.symbol_list:
        raise HTTPException(400, f"symbol must be one of {s.symbol_list}")
    day_s = (day or date.today()).isoformat()
    try:
        return day_chart_payload(db, symbol, day_s)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"chart fetch failed: {exc}") from exc


@app.get("/api/report/{run_id}")
def report(run_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    data = session_get(run_id, db)
    by_pattern: dict[str, int] = {}
    for sig in data["signals"]:
        by_pattern[sig["pattern"]] = by_pattern.get(sig["pattern"], 0) + 1
    closed = [u for u in data["setups"] if str(u["status"]).startswith("closed")]
    return {
        "summary": {
            "session_date": data["run"]["session_date"],
            "feed_is_realtime": False,
            "feed_label": data["run"]["feed_label"],
            "pattern_counts": by_pattern,
            "setups_total": len(data["setups"]),
            "setups_closed": len(closed),
            "note": (
                "One session verifies detector/workflow only — "
                "not durable profitability."
            ),
        },
        "detail": data,
    }
