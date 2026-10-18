"""End-to-end demo: import → train → evaluate → offline pipeline → reports.

Run: python -m scripts.e2e_demo
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.db import models as m
from app.db.session import SessionLocal, engine
from app.db.base import Base
from app.pipeline.orchestrator import run_daily_pipeline
from app.services.ingestion.persist import (
    complete_batch,
    persist_daily_bars,
    persist_intraday_bars,
    start_batch,
)
from app.adapters.market_data.fixture import FixtureMarketDataProvider
from app.services.research import (
    issue_predictions,
    resolve_predictions,
    train_and_register,
)
from datetime import date, datetime, timezone


def main() -> None:
    """Execute demo against the configured database."""
    print("=== LSE Pattern Lab e2e demo (synthetic labelled data) ===")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        provider = FixtureMarketDataProvider(ROOT / "sample_data")
        batch = start_batch(db, provider_key="fixture", session_date=date(2024, 3, 15))
        daily = provider.fetch_daily(
            ["VOD.L", "BP.L", "HSBA.L"], date(2024, 1, 1), date(2024, 6, 1)
        )
        n_d = persist_daily_bars(db, daily, batch)
        intra = provider.fetch_intraday(
            ["VOD.L"],
            datetime(2024, 3, 15, tzinfo=timezone.utc),
            datetime(2024, 3, 16, tzinfo=timezone.utc),
        )
        n_i = persist_intraday_bars(db, intra, batch)
        complete_batch(db, batch)
        db.commit()
        print(f"Imported synthetic daily={n_d} intraday={n_i}")

        train = train_and_register(db)
        print("Train:", train.get("status"), train.get("models"))
        pred = issue_predictions(db)
        print("Predict:", pred)
        resolved = resolve_predictions(db)
        print("Resolve:", resolved)

        result = run_daily_pipeline(db, offline=True, symbols=["VOD.L", "BP.L", "HSBA.L"])
        print("Pipeline:", result.get("status"), result.get("artifact_dir"))

        n_models = len(db.scalars(select(m.ModelRecord)).all())
        print(f"Models in registry: {n_models}")
        print("Demo complete. Synthetic data cannot establish profitability.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
