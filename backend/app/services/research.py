"""High-level research orchestration (train, predict, resolve)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd  # noqa: F401 — used in issue_predictions
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import models as m
from app.domain.enums import ModelStatus
from app.services.eval.costs import load_cost_assumptions
from app.services.features.pipeline import build_daily_features
from app.services.models.train import predict_with_artifact, train_all_models


def load_daily_bars_frame(db: Session) -> pd.DataFrame:
    """Load current daily bars into a feature-ready frame."""
    rows = db.scalars(
        select(m.MarketBarDaily).where(m.MarketBarDaily.is_current.is_(True))
    ).all()
    if not rows:
        return pd.DataFrame()
    records = [
        {
            "session_date": r.session_date,
            "instrument_id": r.instrument_id,
            "open_gbp": r.open_gbp,
            "high_gbp": r.high_gbp,
            "low_gbp": r.low_gbp,
            "close_gbp": r.close_gbp,
            "volume": r.volume,
        }
        for r in rows
    ]
    frame = pd.DataFrame.from_records(records)
    frame = frame.set_index("session_date")
    return frame


def train_and_register(db: Session, artifact_root: Path | None = None) -> dict[str, Any]:
    """Train models from DB bars and register candidates/champion."""
    settings = get_settings()
    frame = load_daily_bars_frame(db)
    if frame.empty or frame["instrument_id"].nunique() < 1:
        return {
            "status": "insufficient_data",
            "message": (
                "Need daily OHLCV market data for at least one instrument "
                "with enough history to build features. Upload CSV or run "
                "provider download."
            ),
        }

    feat = build_daily_features(frame)
    if len(feat.frame) < 30:
        return {
            "status": "insufficient_data",
            "message": (
                f"Only {len(feat.frame)} labelled rows after feature filters; "
                "need more history. Excluded features: "
                f"{feat.excluded or 'none'}"
            ),
            "excluded_features": feat.excluded,
        }

    root = Path(artifact_root or Path(settings.local_storage_root) / "models")
    root.mkdir(parents=True, exist_ok=True)
    results = train_all_models(feat.frame, root, horizon=settings.default_horizon)

    exp = m.Experiment(
        name=f"train-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        config={"horizon": settings.default_horizon, "costs": load_cost_assumptions().to_dict()},
        metrics={"n_rows": len(feat.frame), "excluded": feat.excluded},
    )
    db.add(exp)
    db.flush()

    created = []
    # Promote best linear interpretable by AUC among ridge/logistic as candidate;
    # champion remains manual — auto-set first champion only if none exists.
    existing_champion = db.scalar(
        select(m.ModelRecord).where(m.ModelRecord.status == ModelStatus.CHAMPION)
    )

    for r in results:
        rec = m.ModelRecord(
            version=r.version,
            model_type=r.model_type,
            status=ModelStatus.CANDIDATE,
            artifact_path=r.artifact_path,
            formula=r.formula,
            feature_importance=r.feature_importance,
            train_start=r.train_start,
            train_end=r.train_end,
            horizon=r.horizon,
            experiment_id=exp.id,
            metrics=r.metrics,
        )
        db.add(rec)
        created.append(r.version)

    db.flush()

    if existing_champion is None:
        # Seed champion from logistic if present else naive
        pick = db.scalar(
            select(m.ModelRecord).where(m.ModelRecord.model_type == "logistic")
        ) or db.scalar(
            select(m.ModelRecord).where(m.ModelRecord.model_type == "naive")
        )
        if pick:
            pick.status = ModelStatus.CHAMPION
            pick.promoted_at = datetime.now(timezone.utc)

    db.commit()
    return {
        "status": "ok",
        "experiment_id": exp.id,
        "models": created,
        "excluded_features": feat.excluded,
        "n_rows": len(feat.frame),
        "costs": load_cost_assumptions().to_dict(),
        "note": "Champion promotion remains manual for challengers after the first seed.",
    }


def issue_predictions(db: Session, model_id: int | None = None) -> dict[str, Any]:
    """Issue immutable predictions for latest feature rows using champion/model."""
    if model_id is None:
        model = db.scalar(
            select(m.ModelRecord).where(m.ModelRecord.status == ModelStatus.CHAMPION)
        )
    else:
        model = db.get(m.ModelRecord, model_id)
    if not model:
        return {"status": "insufficient_data", "message": "No champion model"}

    frame = load_daily_bars_frame(db)
    feat = build_daily_features(frame)
    if feat.frame.empty:
        return {"status": "insufficient_data", "message": "No feature rows"}

    # Use last date per instrument as as-of
    latest = feat.frame.sort_index().groupby("instrument_id").tail(1)
    issued = 0
    now = datetime.now(timezone.utc)

    if model.artifact_path and Path(model.artifact_path).exists():
        scores = predict_with_artifact(model.artifact_path, latest)
    elif model.model_type == "momentum" and "mom_20d" in latest.columns:
        scores = latest["mom_20d"].to_numpy()
    else:
        scores = [0.0] * len(latest)

    for i, (idx, row) in enumerate(latest.iterrows()):
        score = float(scores[i])
        prob = float(1 / (1 + pow(2.718281828, -10 * score))) if model.model_type != "logistic" else float(score if 0 <= score <= 1 else 1 / (1 + pow(2.718281828, -10 * score)))
        if model.model_type == "logistic" and model.artifact_path:
            # scores already probabilities
            prob = float(scores[i])
            score = prob - 0.5
        db.add(
            m.Prediction(
                instrument_id=int(row["instrument_id"]),
                model_id=model.id,
                issued_at=now,
                session_date=pd_to_date(idx),
                horizon=model.horizon,
                expected_return=score if model.model_type != "logistic" else prob - 0.5,
                probability_up=prob,
                uncertainty=None,
                features_used={k: float(row[k]) for k in row.index if k in feat.frame.columns and k != "instrument_id" and pd.notna(row[k]) and isinstance(row[k], (int, float))},
                features_excluded=list(feat.excluded.keys()),
            )
        )
        issued += 1
    db.commit()
    return {"status": "ok", "issued": issued, "model_version": model.version}


def resolve_predictions(db: Session) -> dict[str, Any]:
    """Append outcomes for predictions whose next session is observable."""
    frame = load_daily_bars_frame(db)
    if frame.empty:
        return {"resolved": 0}
    feat = build_daily_features(frame)
    # Map (instrument_id, session_date) -> realised target
    targets: dict[tuple[int, Any], float] = {}
    for idx, row in feat.frame.iterrows():
        targets[(int(row["instrument_id"]), pd_to_date(idx))] = float(
            row["target_next_session_oc"]
        )

    pending = db.scalars(
        select(m.Prediction).where(m.Prediction.resolved_at.is_(None))
    ).all()
    resolved = 0
    now = datetime.now(timezone.utc)
    for pred in pending:
        key = (pred.instrument_id, pred.session_date)
        if key not in targets:
            continue
        realised = targets[key]
        pred.realised_return = realised
        if pred.expected_return is not None:
            pred.outcome_correct = (pred.expected_return > 0) == (realised > 0)
        elif pred.probability_up is not None:
            pred.outcome_correct = (pred.probability_up >= 0.5) == (realised > 0)
        pred.resolved_at = now
        resolved += 1
    db.commit()
    return {"resolved": resolved}


def pd_to_date(idx) -> Any:
    """Normalize index value to date."""
    if hasattr(idx, "date"):
        return idx.date()
    return idx
