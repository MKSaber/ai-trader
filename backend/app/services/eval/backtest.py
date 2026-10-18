"""Portfolio-style backtest summary from stored predictions (honest, cost-aware)."""

from __future__ import annotations

from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.services.eval.costs import (
    estimate_round_trip_cost_fraction,
    load_cost_assumptions,
)


def prediction_portfolio_summary(db: Session) -> dict[str, Any]:
    """Score resolved directional forecasts after documented costs.

    This is not a claim of outperformance. Benchmark comparison is unavailable
    until a matching GBP total-return series is uploaded.
    """
    preds = db.scalars(
        select(m.Prediction).where(m.Prediction.realised_return.is_not(None))
    ).all()
    if not preds:
        return {
            "status": "insufficient_data",
            "message": "No resolved predictions with realised returns.",
            "benchmark": "benchmark comparison unavailable",
        }

    assumptions = load_cost_assumptions()
    cost = estimate_round_trip_cost_fraction(assumptions)
    # Long when expected_return > 0 or prob >= 0.5; else flat
    gross = []
    net = []
    for p in preds:
        signal = 0
        if p.expected_return is not None:
            signal = 1 if p.expected_return > 0 else 0
        elif p.probability_up is not None:
            signal = 1 if p.probability_up >= 0.5 else 0
        r = float(p.realised_return or 0.0)
        g = signal * r
        n = signal * (r - cost) if signal else 0.0
        gross.append(g)
        net.append(n)

    gross_arr = np.array(gross)
    net_arr = np.array(net)
    equity = np.cumprod(1.0 + net_arr)
    peak = np.maximum.accumulate(equity)
    dd = (equity / peak) - 1.0

    return {
        "status": "ok",
        "n": len(preds),
        "costs": assumptions.to_dict(),
        "round_trip_cost_fraction": cost,
        "gross_mean": float(np.mean(gross_arr)),
        "net_mean": float(np.mean(net_arr)),
        "net_total_compounded": float(equity[-1] - 1.0),
        "volatility": float(np.std(net_arr)) if len(net_arr) > 1 else None,
        "max_drawdown": float(np.min(dd)) if len(dd) else None,
        "hit_rate_when_long": float(
            np.mean([1 if g > 0 else 0 for g in gross if g != 0] or [0])
        ),
        "benchmark": "benchmark comparison unavailable",
        "note": (
            "Prediction quality and portfolio P&L are reported separately. "
            "Overlapping labels are not annualised as independent observations."
        ),
    }


def pattern_hypotheses(db: Session) -> list[dict[str, Any]]:
    """Surface exploratory pattern cards from findings + simple momentum check."""
    findings = db.scalars(
        select(m.ResearchFinding).order_by(m.ResearchFinding.id.desc()).limit(50)
    ).all()
    cards = []
    for f in findings:
        cards.append(
            {
                "kind": "finding",
                "claim": f.claim,
                "status": f.status,
                "sample_size": f.sample_size,
                "evidence_label": f.status,
                "note": "Exploratory unless status=validated.",
            }
        )
    # Momentum hypothesis from resolved preds if available
    preds = [
        p
        for p in db.scalars(select(m.Prediction)).all()
        if p.realised_return is not None and p.expected_return is not None
    ]
    if len(preds) >= 10:
        agree = sum(
            1
            for p in preds
            if (p.expected_return > 0) == (p.realised_return > 0)
        )
        cards.append(
            {
                "kind": "hypothesis",
                "claim": (
                    f"Directional agreement on resolved forecasts: "
                    f"{agree}/{len(preds)} ({agree / len(preds):.0%})."
                ),
                "status": "exploratory",
                "sample_size": len(preds),
                "evidence_label": "exploratory",
                "note": "Out-of-sample directional agreement ≠ profitable edge after costs.",
            }
        )
    return cards
