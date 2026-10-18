"""ARQ background worker settings."""

from __future__ import annotations

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.pipeline.orchestrator import run_daily_pipeline
from app.services.research import train_and_register


async def job_train(ctx: dict) -> dict:
    """Background training with DB session."""
    del ctx
    db = SessionLocal()
    try:
        return train_and_register(db)
    finally:
        db.close()


async def job_daily_pipeline(ctx: dict, offline: bool = False) -> dict:
    """Background daily pipeline."""
    del ctx
    db = SessionLocal()
    try:
        return run_daily_pipeline(db, offline=offline)
    finally:
        db.close()


class WorkerSettings:
    """ARQ worker configuration."""

    functions = [job_train, job_daily_pipeline]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 1  # protect against duplicate heavy training
