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
from app.services.eval.rolling import run_rolling_walkforward
from app.services.models.train import (
    holdout_success_verdict,
    predict_with_artifact,
    train_all_models,
)


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

    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    exp = m.Experiment(
        name=f"train-{run_stamp}",
        config={
            "horizon": settings.default_horizon,
            "costs": load_cost_assumptions().to_dict(),
        },
        metrics={"n_rows": len(feat.frame), "excluded": feat.excluded},
    )
    db.add(exp)
    db.flush()

    created: list[str] = []
    skipped: list[str] = []
    # Champion remains manual — auto-set first champion only if none exists.
    existing_champion = db.scalar(
        select(m.ModelRecord).where(m.ModelRecord.status == ModelStatus.CHAMPION)
    )

    for r in results:
        # Content digest alone can collide on retrain with same data —
        # suffix each registration with the experiment run stamp.
        version = f"{r.version}-r{run_stamp}"
        already = db.scalar(
            select(m.ModelRecord).where(m.ModelRecord.version == version)
        )
        if already:
            skipped.append(version)
            continue
        rec = m.ModelRecord(
            version=version,
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
        created.append(version)

    db.flush()

    if existing_champion is None and created:
        # Seed champion from this run's logistic if present else first created
        pick = db.scalar(
            select(m.ModelRecord).where(
                m.ModelRecord.experiment_id == exp.id,
                m.ModelRecord.model_type == "logistic",
            )
        ) or db.scalar(
            select(m.ModelRecord).where(m.ModelRecord.experiment_id == exp.id)
        )
        if pick:
            pick.status = ModelStatus.CHAMPION
            pick.promoted_at = datetime.now(timezone.utc)

    db.commit()
    return {
        "status": "ok",
        "experiment_id": exp.id,
        "models": created,
        "skipped": skipped,
        "excluded_features": feat.excluded,
        "n_rows": len(feat.frame),
        "costs": load_cost_assumptions().to_dict(),
        "note": (
            "Champion promotion remains manual for challengers after the first seed. "
            "Each train run registers new version tags even if formulas are identical."
        ),
    }


def run_holdout_eval(
    db: Session,
    *,
    train_sessions: int = 90,
    test_sessions: int = 5,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Train on prior N sessions; score the most recent M sessions.

    Returns a transparent pass/fail gate on directional accuracy vs naive.
    Passing is not a claim of profitable edge after costs.
    """
    settings = get_settings()
    frame = load_daily_bars_frame(db)
    if frame.empty:
        return {
            "status": "insufficient_data",
            "message": "No daily bars. Fetch from Yahoo first.",
        }

    feat = build_daily_features(frame)
    uniq_sessions = (
        pd.to_datetime(feat.frame.index).normalize().unique()
        if not feat.frame.empty
        else []
    )
    need = train_sessions + test_sessions
    if len(uniq_sessions) < need:
        return {
            "status": "insufficient_data",
            "message": (
                f"Need >= {need} labelled trading sessions for "
                f"{train_sessions} train + {test_sessions} test; "
                f"have {len(uniq_sessions)}. Fetch more Yahoo history "
                f"(~{need + 30} calendar days recommended for feature warm-up)."
            ),
            "unique_sessions": int(len(uniq_sessions)),
            "excluded_features": feat.excluded,
        }

    root = Path(artifact_root or Path(settings.local_storage_root) / "models")
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    out_dir = root / f"holdout-{train_sessions}-{test_sessions}-{run_stamp}"
    try:
        results = train_all_models(
            feat.frame,
            out_dir,
            horizon=settings.default_horizon,
            train_sessions=train_sessions,
            test_sessions=test_sessions,
        )
    except ValueError as exc:
        return {"status": "insufficient_data", "message": str(exc)}

    exp = m.Experiment(
        name=f"holdout-{train_sessions}-{test_sessions}-{run_stamp}",
        config={
            "horizon": settings.default_horizon,
            "train_sessions": train_sessions,
            "test_sessions": test_sessions,
            "costs": load_cost_assumptions().to_dict(),
            "protocol": "fixed_session_holdout",
        },
        metrics={},
    )
    db.add(exp)
    db.flush()

    model_summaries: list[dict[str, Any]] = []
    created: list[str] = []
    for r in results:
        version = f"{r.version}-h{train_sessions}x{test_sessions}-r{run_stamp}"
        already = db.scalar(
            select(m.ModelRecord).where(m.ModelRecord.version == version)
        )
        if already:
            continue
        rec = m.ModelRecord(
            version=version,
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
        created.append(version)
        model_summaries.append(
            {
                "model_type": r.model_type,
                "version": version,
                "accuracy": (r.metrics or {}).get("accuracy"),
                "auc": (r.metrics or {}).get("auc"),
                "r2": (r.metrics or {}).get("r2"),
                "pearson_ic": (r.metrics or {}).get("pearson_ic"),
                "n": (r.metrics or {}).get("n"),
                "n_train": (r.metrics or {}).get("n_train"),
                "n_test": (r.metrics or {}).get("n_test"),
                "holdout": (r.metrics or {}).get("holdout"),
            }
        )

    verdict = holdout_success_verdict(model_summaries)
    exp.metrics = {
        "verdict": verdict,
        "models": model_summaries,
        "n_feature_rows": len(feat.frame),
    }
    db.commit()

    return {
        "status": "ok",
        "experiment_id": exp.id,
        "protocol": {
            "train_sessions": train_sessions,
            "test_sessions": test_sessions,
            "holdout": (model_summaries[0].get("holdout") if model_summaries else None),
        },
        "models": model_summaries,
        "registered": created,
        "success": verdict,
        "excluded_features": feat.excluded,
        "costs": load_cost_assumptions().to_dict(),
        "note": (
            "Trained only on sessions before the test window. "
            "Test metrics are out-of-sample for those last sessions. "
            "success.passed is a directional gate, not a profit claim."
        ),
    }


def run_rolling_eval(
    db: Session,
    *,
    train_sessions: int = 85,
    test_sessions: int = 5,
    step_sessions: int = 5,
    max_folds: int | None = None,
    min_prob: float = 0.55,
) -> dict[str, Any]:
    """Rolling 85/5 walk-forward with stop/TP paper scoring + tips."""
    settings = get_settings()
    frame = load_daily_bars_frame(db)
    if frame.empty:
        return {
            "status": "insufficient_data",
            "message": "No daily bars. Fetch ~5y from Yahoo first.",
        }
    feat = build_daily_features(frame)
    uniq = (
        len(pd.to_datetime(feat.frame.index).normalize().unique())
        if not feat.frame.empty
        else 0
    )
    need = train_sessions + test_sessions
    if uniq < need:
        return {
            "status": "insufficient_data",
            "message": (
                f"Need >= {need} labelled sessions for rolling "
                f"{train_sessions}/{test_sessions}; have {uniq}. "
                "Fetch lookback_days=1825 (5y)."
            ),
            "unique_sessions": uniq,
        }

    result = run_rolling_walkforward(
        feat.frame,
        frame,
        train_sessions=train_sessions,
        test_sessions=test_sessions,
        step_sessions=step_sessions,
        max_folds=max_folds,
        min_prob=min_prob,
        artifact_dir=Path(settings.local_storage_root) / "models" / "rolling",
    )

    # Enrich recommendations with yahoo symbols
    id_to_sym = {
        r.id: r.yahoo_symbol
        for r in db.scalars(select(m.Instrument)).all()
    }
    for tip in result.get("recommendations") or []:
        tip["symbol"] = id_to_sym.get(tip.get("instrument_id"), tip.get("instrument_id"))
    for trade in result.get("sample_trades") or []:
        trade["symbol"] = id_to_sym.get(
            trade.get("instrument_id"), trade.get("instrument_id")
        )

    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    exp = m.Experiment(
        name=f"rolling-{train_sessions}x{test_sessions}-{run_stamp}",
        config={
            "protocol": "rolling_walkforward",
            "train_sessions": train_sessions,
            "test_sessions": test_sessions,
            "step_sessions": step_sessions,
            "min_prob": min_prob,
            "costs": load_cost_assumptions().to_dict(),
        },
        metrics={
            "direction_success": result.get("direction_success"),
            "trading": result.get("trading"),
            "models": result.get("models"),
            "protocol": result.get("protocol"),
        },
    )
    db.add(exp)
    db.commit()
    result["experiment_id"] = exp.id
    return result


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
