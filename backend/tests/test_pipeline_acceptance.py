"""Pipeline / learning acceptance behaviours (DB-backed where needed)."""

from datetime import date, datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.adapters.factory import get_market_data_provider
from app.adapters.market_data.yfinance_provider import YFinanceMarketDataProvider
from app.core.config import Settings
from app.db.base import Base
from app.db import models as m
from app.domain.enums import ModelStatus
from app.services.findings.service import search_findings, upsert_finding


def test_live_provider_is_not_fixture_by_default() -> None:
    """yfinance is selected when not offline — never silent fixture."""
    settings = Settings(market_data_provider="yfinance", demo_mode=False)
    provider = get_market_data_provider(settings, force_offline=False)
    assert isinstance(provider, YFinanceMarketDataProvider)
    assert provider.name == "yfinance"


def test_offline_explicit_fixture() -> None:
    """Fixture only when offline/demo is explicit."""
    settings = Settings(market_data_provider="yfinance", demo_mode=False)
    provider = get_market_data_provider(settings, force_offline=True)
    assert provider.name == "fixture"


def test_challenger_reject_leaves_champion() -> None:
    """Rejecting a challenger does not change the champion."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        champ = m.ModelRecord(
            version="champ-1",
            model_type="logistic",
            status=ModelStatus.CHAMPION,
            horizon="next_session_open_to_close",
            train_start=date(2024, 1, 1),
            train_end=date(2024, 2, 1),
        )
        chall = m.ModelRecord(
            version="chall-1",
            model_type="ridge",
            status=ModelStatus.CANDIDATE,
            horizon="next_session_open_to_close",
            train_start=date(2024, 1, 1),
            train_end=date(2024, 2, 1),
        )
        db.add_all([champ, chall])
        db.commit()
        chall.status = ModelStatus.REJECTED
        db.commit()
        still = db.scalar(
            select(m.ModelRecord).where(m.ModelRecord.status == ModelStatus.CHAMPION)
        )
        assert still is not None
        assert still.version == "champ-1"
        rejected = db.scalar(
            select(m.ModelRecord).where(m.ModelRecord.version == "chall-1")
        )
        assert rejected.status == ModelStatus.REJECTED
    finally:
        db.close()


def test_finding_dedupe_not_new_confirmation() -> None:
    """Re-upserting the same claim updates review date, not a second finding."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        a = upsert_finding(db, claim="same claim", topic="t", sample_size=10)
        b = upsert_finding(db, claim="same claim", topic="t", sample_size=10)
        db.commit()
        assert a.id == b.id
        rows = search_findings(db)
        assert len(rows) == 1
        assert "not established truth" in rows[0]["note"].lower()
    finally:
        db.close()


def test_prediction_outcome_append_only() -> None:
    """Resolving a prediction does not change issued forecast fields."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        inst = m.Instrument(symbol="VOD", yahoo_symbol="VOD.L")
        model = m.ModelRecord(
            version="m1",
            model_type="naive",
            status=ModelStatus.CHAMPION,
            horizon="next_session_open_to_close",
        )
        db.add_all([inst, model])
        db.flush()
        pred = m.Prediction(
            instrument_id=inst.id,
            model_id=model.id,
            issued_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
            session_date=date(2024, 1, 2),
            horizon="next_session_open_to_close",
            expected_return=0.01,
            probability_up=0.6,
        )
        db.add(pred)
        db.commit()
        issued = pred.expected_return
        pred.realised_return = -0.02
        pred.outcome_correct = False
        pred.resolved_at = datetime.now(timezone.utc)
        db.commit()
        again = db.get(m.Prediction, pred.id)
        assert again.expected_return == issued
        assert again.realised_return == -0.02
    finally:
        db.close()
