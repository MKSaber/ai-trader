"""Research findings helpers — claims are not established truth."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.domain.enums import FindingStatus


def upsert_finding(
    db: Session,
    *,
    claim: str,
    topic: str,
    horizon: str | None = None,
    sample_size: int | None = None,
    effect_size: float | None = None,
    data_cutoff: date | None = None,
    status: str = FindingStatus.EXPLORATORY,
    experiment_ids: list[int] | None = None,
) -> m.ResearchFinding:
    """Store a finding; identical claim+topic updates review date only."""
    existing = db.scalar(
        select(m.ResearchFinding).where(
            m.ResearchFinding.claim == claim,
            m.ResearchFinding.topic == topic,
        )
    )
    today = date.today()
    if existing:
        existing.last_review_date = today
        # Do not treat re-observation as independent confirmation
        db.flush()
        return existing
    row = m.ResearchFinding(
        claim=claim,
        universe="LSE sample",
        horizon=horizon,
        discovery_date=today,
        data_cutoff=data_cutoff or today,
        sample_size=sample_size,
        effect_size=effect_size,
        experiment_ids=experiment_ids or [],
        status=status,
        last_review_date=today,
        topic=topic,
        search_vector=f"{claim} {topic}",
    )
    db.add(row)
    db.flush()
    return row


def search_findings(db: Session, q: str | None = None) -> list[dict[str, Any]]:
    """List findings with optional text filter."""
    rows = db.scalars(
        select(m.ResearchFinding).order_by(m.ResearchFinding.id.desc()).limit(200)
    ).all()
    out = []
    for f in rows:
        blob = f"{f.claim} {f.search_vector or ''} {f.topic or ''}".lower()
        if q and q.lower() not in blob:
            continue
        out.append(
            {
                "id": f.id,
                "claim": f.claim,
                "status": f.status,
                "horizon": f.horizon,
                "discovery_date": f.discovery_date.isoformat(),
                "data_cutoff": f.data_cutoff.isoformat(),
                "sample_size": f.sample_size,
                "effect_size": f.effect_size,
                "topic": f.topic,
                "last_review_date": (
                    f.last_review_date.isoformat() if f.last_review_date else None
                ),
                "note": (
                    "A stored finding is not established truth. "
                    "Re-seeing the same observations is not new confirmation."
                ),
            }
        )
    return out
