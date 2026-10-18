"""Simple feature / performance drift checks."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.services.features.pipeline import build_daily_features
from app.services.research import load_daily_bars_frame


def compute_drift_report(db: Session) -> dict[str, Any]:
    """Compare recent vs earlier feature means; flag large shifts."""
    frame = load_daily_bars_frame(db)
    if frame.empty:
        return {
            "status": "insufficient_data",
            "message": "Need daily bars before drift can be assessed.",
            "alerts": [],
        }
    feat = build_daily_features(frame)
    if len(feat.frame) < 40:
        return {
            "status": "insufficient_data",
            "message": f"Only {len(feat.frame)} feature rows; need more history.",
            "alerts": [],
        }
    f = feat.frame.sort_index()
    mid = len(f) // 2
    early = f.iloc[:mid]
    late = f.iloc[mid:]
    cols = [
        c
        for c in ("ret_1d", "mom_20d", "rvol_20", "ma_gap_20")
        if c in f.columns
    ]
    alerts: list[dict[str, Any]] = []
    comparisons: dict[str, Any] = {}
    for c in cols:
        e_mean = float(np.nanmean(early[c]))
        l_mean = float(np.nanmean(late[c]))
        e_std = float(np.nanstd(early[c])) or 1e-9
        z = abs(l_mean - e_mean) / e_std
        comparisons[c] = {
            "early_mean": e_mean,
            "late_mean": l_mean,
            "shift_z": z,
        }
        if z > 2.0:
            alerts.append(
                {
                    "feature": c,
                    "severity": "high",
                    "message": (
                        f"{c} late-window mean shifted by z={z:.2f} vs early window. "
                        "Investigate before promoting models — drift is not auto-deploy."
                    ),
                }
            )

    # Forecast performance drift
    preds = db.scalars(
        select(m.Prediction).where(m.Prediction.resolved_at.is_not(None))
    ).all()
    if len(preds) >= 10:
        half = len(preds) // 2
        early_acc = np.mean(
            [1.0 if p.outcome_correct else 0.0 for p in preds[:half]]
        )
        late_acc = np.mean(
            [1.0 if p.outcome_correct else 0.0 for p in preds[half:]]
        )
        comparisons["forecast_accuracy"] = {
            "early": float(early_acc),
            "late": float(late_acc),
        }
        if abs(late_acc - early_acc) > 0.15:
            alerts.append(
                {
                    "feature": "forecast_accuracy",
                    "severity": "medium",
                    "message": (
                        f"Resolved forecast accuracy moved from {early_acc:.0%} "
                        f"to {late_acc:.0%}. Queue investigation / candidate retrain."
                    ),
                }
            )

    return {
        "status": "ok" if not alerts else "alerts",
        "comparisons": comparisons,
        "alerts": alerts,
        "n_feature_rows": len(f),
        "n_resolved_predictions": len(preds),
        "note": "Drift triggers investigation — not automatic deployment.",
    }
