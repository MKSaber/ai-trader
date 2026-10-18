"""Daily research pipeline orchestrator — 14 idempotent stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.adapters.factory import get_calendar, get_market_data_provider, get_object_storage
from app.core.config import get_settings
from app.db import models as m
from app.domain.enums import FindingStatus, PipelineRunStatus, StageStatus
from app.reporting.daily import write_artifact_bundle
from app.services.eval.costs import load_cost_assumptions
from app.services.ingestion.persist import (
    complete_batch,
    persist_daily_bars,
    persist_intraday_bars,
    start_batch,
)
from app.services.intraday.engine import (
    generate_long_setup,
    portfolio_metrics,
    simulate_setup,
)
from app.services.findings.service import upsert_finding
from app.services.research import issue_predictions, resolve_predictions, train_and_register
import pandas as pd


STAGE_NAMES = [
    "create_run_lock",
    "check_config",
    "missing_sessions",
    "download_validate",
    "store_records",
    "resolve_predictions",
    "replay_sessions",
    "update_ledger",
    "analyse_errors",
    "retrain_challenger",
    "evaluate_challengers",
    "save_findings",
    "generate_reports",
    "finalize",
]


@dataclass
class PipelineContext:
    """Shared mutable context across stages."""

    db: Session
    session_date: date | None
    catchup_from: date | None
    catchup_to: date | None
    dry_run: bool
    offline: bool
    run: m.PipelineRun | None = None
    missing_sessions: list[date] = field(default_factory=list)
    download_stats: dict[str, Any] = field(default_factory=dict)
    replay_stats: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    artifact_dir: Path | None = None
    failed: bool = False
    error_summary: str | None = None


def _set_stage(
    db: Session,
    run: m.PipelineRun,
    name: str,
    status: str,
    detail: dict | None = None,
    error: str | None = None,
) -> None:
    row = db.scalar(
        select(m.PipelineStageStatus).where(
            m.PipelineStageStatus.run_id == run.id,
            m.PipelineStageStatus.stage_name == name,
        )
    )
    now = datetime.now(timezone.utc)
    if row is None:
        row = m.PipelineStageStatus(run_id=run.id, stage_name=name)
        db.add(row)
    row.status = status
    if status == StageStatus.RUNNING:
        row.started_at = now
    if status in {StageStatus.SUCCESS, StageStatus.FAILED, StageStatus.SKIPPED}:
        row.finished_at = now
    row.detail = detail
    row.error = error
    db.commit()


def run_daily_pipeline(
    db: Session,
    *,
    session_date: date | None = None,
    catchup_from: date | None = None,
    catchup_to: date | None = None,
    dry_run: bool = False,
    offline: bool = False,
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Execute the full daily research sequence."""
    ctx = PipelineContext(
        db=db,
        session_date=session_date,
        catchup_from=catchup_from,
        catchup_to=catchup_to,
        dry_run=dry_run,
        offline=offline,
    )
    ctx.download_stats["symbols"] = symbols or ["VOD.L", "BP.L", "HSBA.L", "GSK.L", "AZN.L"]

    stages: list[tuple[str, Callable[[PipelineContext], None]]] = [
        ("create_run_lock", stage_create_run_lock),
        ("check_config", stage_check_config),
        ("missing_sessions", stage_missing_sessions),
        ("download_validate", stage_download_validate),
        ("store_records", stage_store_records),
        ("resolve_predictions", stage_resolve_predictions),
        ("replay_sessions", stage_replay_sessions),
        ("update_ledger", stage_update_ledger),
        ("analyse_errors", stage_analyse_errors),
        ("retrain_challenger", stage_retrain_challenger),
        ("evaluate_challengers", stage_evaluate_challengers),
        ("save_findings", stage_save_findings),
        ("generate_reports", stage_generate_reports),
        ("finalize", stage_finalize),
    ]

    for name, fn in stages:
        if ctx.run is None and name != "create_run_lock":
            break
        if ctx.run:
            _set_stage(db, ctx.run, name, StageStatus.RUNNING)
        try:
            fn(ctx)
            if ctx.run:
                _set_stage(db, ctx.run, name, StageStatus.SUCCESS, detail={"ok": True})
        except Exception as exc:  # noqa: BLE001
            ctx.failed = True
            ctx.error_summary = f"{name}: {exc}"
            if ctx.run:
                _set_stage(
                    db, ctx.run, name, StageStatus.FAILED, error=str(exc)
                )
            # Continue to generate_reports / finalize for failure artifacts
            if name not in {"generate_reports", "finalize"}:
                # jump toward reporting
                continue

    status = (
        PipelineRunStatus.FAILED
        if ctx.failed
        else PipelineRunStatus.SUCCESS
    )
    return {
        "run_key": ctx.run.run_key if ctx.run else None,
        "status": status,
        "warnings": ctx.warnings,
        "metrics": ctx.metrics,
        "artifact_dir": str(ctx.artifact_dir) if ctx.artifact_dir else None,
        "error_summary": ctx.error_summary,
        "download_stats": ctx.download_stats,
        "replay_stats": ctx.replay_stats,
    }


def stage_create_run_lock(ctx: PipelineContext) -> None:
    """Create run record and acquire advisory lock."""
    db = ctx.db
    # Postgres advisory lock
    lock_key = 82451233
    got = db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key}).scalar()
    if not got:
        raise RuntimeError("Pipeline lock held by another run")
    run_key = f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:6]}"
    run = m.PipelineRun(
        run_key=run_key,
        session_date=ctx.session_date,
        status=PipelineRunStatus.RUNNING,
        dry_run=ctx.dry_run,
        offline=ctx.offline,
        manifest={"stages": STAGE_NAMES},
    )
    db.add(run)
    db.commit()
    ctx.run = run
    for name in STAGE_NAMES:
        db.add(
            m.PipelineStageStatus(
                run_id=run.id, stage_name=name, status=StageStatus.PENDING
            )
        )
    db.commit()


def stage_check_config(ctx: PipelineContext) -> None:
    """Validate configuration and provider availability."""
    settings = get_settings()
    provider = get_market_data_provider(force_offline=ctx.offline)
    ok, msg = provider.healthcheck()
    if not ok and not ctx.offline:
        raise RuntimeError(f"Provider unavailable: {msg}")
    if not ok:
        ctx.warnings.append(msg)
    ctx.download_stats["provider"] = provider.name
    ctx.download_stats["provider_health"] = msg
    ctx.download_stats["costs"] = load_cost_assumptions(settings).to_dict()
    # Object storage touch
    store = get_object_storage()
    store.put_bytes(
        f"pipeline/{ctx.run.run_key}/.keepalive",
        b"ok",
        content_type="text/plain",
    )


def stage_missing_sessions(ctx: PipelineContext) -> None:
    """Determine missing completed sessions (calendar-aware)."""
    cal = get_calendar()
    today = date.today()
    # Default: previous session
    target = ctx.session_date or cal.previous_session(today - timedelta(days=1))
    start = ctx.catchup_from or target
    end = ctx.catchup_to or target
    sessions = cal.sessions_between(start, end)
    # Filter to completed sessions only (before today or verified)
    completed = [s for s in sessions if s < today or s == target]
    ctx.missing_sessions = completed
    ctx.session_date = target
    ctx.download_stats["target_session"] = target.isoformat()
    ctx.download_stats["sessions"] = [s.isoformat() for s in completed]


def stage_download_validate(ctx: PipelineContext) -> None:
    """Download new data; never substitute synthetic on live failure."""
    if ctx.dry_run:
        ctx.warnings.append("Dry run: skipping download")
        return
    provider = get_market_data_provider(force_offline=ctx.offline)
    symbols = ctx.download_stats["symbols"]
    if not ctx.missing_sessions:
        ctx.warnings.append("No sessions to download")
        return
    start = min(ctx.missing_sessions)
    end = max(ctx.missing_sessions)
    daily = provider.fetch_daily(symbols, start, end)
    # Intraday for latest session only (within lookback)
    from datetime import time
    from zoneinfo import ZoneInfo

    london = ZoneInfo("Europe/London")
    last = end
    start_dt = datetime.combine(last, time(7, 0), tzinfo=london)
    end_dt = datetime.combine(last, time(17, 0), tzinfo=london)
    intraday = provider.fetch_intraday(
        symbols, start_dt, end_dt, interval_minutes=get_settings().intraday_interval_minutes
    )
    if not daily and provider.name == "yfinance" and not ctx.offline:
        raise RuntimeError(
            "yfinance returned no daily bars. Not substituting synthetic data. "
            "Check connectivity/symbols or use --offline for fixture demos."
        )
    ctx.download_stats["daily_bars"] = len(daily)
    ctx.download_stats["intraday_bars"] = len(intraday)
    ctx.download_stats["_daily"] = daily
    ctx.download_stats["_intraday"] = intraday
    if not intraday:
        ctx.warnings.append(
            "No intraday bars available — intraday predictions will be disabled "
            "for this run. Recent ~60-day Yahoo history may not cover the session."
        )


def stage_store_records(ctx: PipelineContext) -> None:
    """Store raw refs and normalised records."""
    if ctx.dry_run:
        return
    daily = ctx.download_stats.pop("_daily", [])
    intraday = ctx.download_stats.pop("_intraday", [])
    provider_key = ctx.download_stats.get("provider", "unknown")
    batch = start_batch(
        ctx.db, provider_key=provider_key, session_date=ctx.session_date
    )
    n_d = persist_daily_bars(ctx.db, daily, batch)
    n_i = persist_intraday_bars(
        ctx.db,
        intraday,
        batch,
        interval_minutes=get_settings().intraday_interval_minutes,
    )
    complete_batch(ctx.db, batch)
    ctx.db.commit()
    ctx.download_stats["stored_daily"] = n_d
    ctx.download_stats["stored_intraday"] = n_i


def stage_resolve_predictions(ctx: PipelineContext) -> None:
    """Resolve prior predictions with observable outcomes."""
    result = resolve_predictions(ctx.db)
    ctx.metrics["resolved_predictions"] = result


def stage_replay_sessions(ctx: PipelineContext) -> None:
    """Replay eligible sessions with as-of models; freeze setups."""
    assumptions = load_cost_assumptions()
    settings = get_settings()
    # Load intraday bars
    bars = ctx.db.scalars(
        select(m.MarketBarIntraday).where(m.MarketBarIntraday.is_current.is_(True))
    ).all()
    if not bars:
        ctx.warnings.append(
            "Intraday replay skipped: no intraday bars in database"
        )
        ctx.replay_stats = {"setups": 0, "note": "insufficient_intraday_data"}
        return

    inst_map = {
        i.id: i
        for i in ctx.db.scalars(select(m.Instrument)).all()
    }
    champion = ctx.db.scalar(
        select(m.ModelRecord).where(m.ModelRecord.status == "champion")
    )
    model_version = champion.version if champion else "none"

    records = []
    for b in bars:
        inst = inst_map.get(b.instrument_id)
        records.append(
            {
                "instrument_id": b.instrument_id,
                "symbol": inst.yahoo_symbol if inst else str(b.instrument_id),
                "bar_ts": b.bar_ts,
                "open_gbp": b.open_gbp,
                "high_gbp": b.high_gbp,
                "low_gbp": b.low_gbp,
                "close_gbp": b.close_gbp,
                "volume": b.volume,
            }
        )
    frame = pd.DataFrame.from_records(records)
    setups_n = 0
    trade_rows: list[dict[str, Any]] = []

    cash = settings.initial_paper_cash_gbp
    open_positions = 0
    max_positions = 3

    for inst_id, group in frame.groupby("instrument_id"):
        g = group.sort_values("bar_ts").reset_index(drop=True)
        # Sample signals every 12 bars (~1h at 5m)
        for idx in range(12, len(g) - 2, 12):
            if open_positions >= max_positions:
                break
            spec = generate_long_setup(
                g, idx, model_version=model_version, assumptions=assumptions
            )
            # Idempotent: skip if setup already exists at signal_ts
            existing = ctx.db.scalar(
                select(m.IntradaySetup).where(
                    m.IntradaySetup.instrument_id == int(inst_id),
                    m.IntradaySetup.signal_ts == spec.signal_ts,
                    m.IntradaySetup.model_version == model_version,
                )
            )
            if existing:
                continue
            setup = m.IntradaySetup(
                instrument_id=int(inst_id),
                model_id=champion.id if champion else None,
                signal_ts=spec.signal_ts,
                model_version=model_version,
                side="long",
                entry_low=spec.entry_low,
                entry_high=spec.entry_high,
                entry_expiry=spec.entry_expiry,
                stop_loss=spec.stop_loss,
                take_profit=spec.take_profit,
                max_hold_minutes=spec.max_hold_minutes,
                expected_net_return=spec.expected_net_return,
                uncertainty=spec.uncertainty,
                estimated_costs=spec.estimated_costs,
                reason=spec.reason,
                no_trade=spec.no_trade,
            )
            ctx.db.add(setup)
            ctx.db.flush()
            setups_n += 1
            sim = simulate_setup(spec, g, assumptions)
            setup.outcome = sim.outcome
            setup.exit_reason = sim.exit_reason
            setup.ambiguity_flag = sim.ambiguity_flag
            if sim.entry_ts and sim.net_pnl is not None:
                open_positions += 1
                pos = m.PaperPosition(
                    setup_id=setup.id,
                    instrument_id=int(inst_id),
                    quantity=5000.0 / (sim.entry_price or 1),
                    entry_price=sim.entry_price or 0,
                    exit_price=sim.exit_price,
                    opened_at=sim.entry_ts,
                    closed_at=sim.exit_ts,
                    gross_pnl=sim.gross_pnl,
                    costs=sim.costs,
                    net_pnl=sim.net_pnl,
                    exit_reason=sim.exit_reason,
                    ambiguity_flag=sim.ambiguity_flag,
                )
                ctx.db.add(pos)
                cash += float(sim.net_pnl or 0)
                open_positions -= 1
                trade_rows.append(
                    {
                        "net_pnl": sim.net_pnl,
                        "gross_pnl": sim.gross_pnl,
                        "costs": sim.costs,
                    }
                )
    ctx.db.commit()
    ctx.replay_stats = {
        "setups": setups_n,
        "trades": portfolio_metrics(trade_rows),
        "ending_cash": cash,
    }
    ctx.metrics["paper"] = ctx.replay_stats


def stage_update_ledger(ctx: PipelineContext) -> None:
    """Update paper ledger snapshot."""
    cash = ctx.replay_stats.get("ending_cash", get_settings().initial_paper_cash_gbp)
    ctx.db.add(
        m.PaperLedger(
            as_of=datetime.now(timezone.utc),
            cash_gbp=float(cash),
            exposure_gbp=0.0,
            equity_gbp=float(cash),
            notes=f"run={ctx.run.run_key if ctx.run else ''}",
        )
    )
    ctx.db.commit()


def stage_analyse_errors(ctx: PipelineContext) -> None:
    """Analyse errors / drift at a high level."""
    preds = ctx.db.scalars(
        select(m.Prediction).where(m.Prediction.resolved_at.is_not(None))
    ).all()
    if not preds:
        claim = "No resolved predictions yet to analyse forecast errors"
        upsert_finding(
            ctx.db,
            claim=claim,
            topic="daily_pipeline",
            data_cutoff=ctx.session_date,
            status=FindingStatus.EXPLORATORY,
        )
        ctx.findings.append({"claim": claim, "status": FindingStatus.EXPLORATORY})
        return
    correct = sum(1 for p in preds if p.outcome_correct)
    n = len(preds)
    claim = (
        f"Among {n} resolved forecasts, {correct} matched direction "
        f"({correct / n:.1%}). Directional accuracy is not net profitability "
        "after costs."
    )
    upsert_finding(
        ctx.db,
        claim=claim,
        topic="daily_pipeline",
        sample_size=n,
        effect_size=correct / n,
        data_cutoff=ctx.session_date,
        status=FindingStatus.EXPLORATORY,
    )
    ctx.findings.append(
        {
            "claim": claim,
            "status": FindingStatus.EXPLORATORY,
            "sample_size": n,
            "effect_size": correct / n,
        }
    )


def stage_retrain_challenger(ctx: PipelineContext) -> None:
    """Retrain only when enough labelled data exists."""
    resolved = ctx.db.scalars(
        select(m.Prediction).where(m.Prediction.resolved_at.is_not(None))
    ).all()
    # Predefined criterion: at least 20 resolved labels OR first train
    models = ctx.db.scalars(select(m.ModelRecord)).all()
    if models and len(resolved) < 20:
        ctx.warnings.append(
            "Challenger retrain skipped: predefined criterion not met "
            f"(resolved={len(resolved)} < 20)"
        )
        ctx.metrics["retrain"] = "skipped"
        return
    result = train_and_register(ctx.db)
    ctx.metrics["retrain"] = result
    if result.get("status") == "insufficient_data":
        ctx.warnings.append(result.get("message", "insufficient data"))


def stage_evaluate_challengers(ctx: PipelineContext) -> None:
    """Compare challengers to champion without auto-promotion."""
    champion = ctx.db.scalar(
        select(m.ModelRecord).where(m.ModelRecord.status == "champion")
    )
    challengers = ctx.db.scalars(
        select(m.ModelRecord).where(m.ModelRecord.status == "candidate")
    ).all()
    if not challengers:
        ctx.metrics["promotion"] = {"recommendation": "none", "reason": "no candidates"}
        return
    # Pick latest non-naive challenger
    cand = sorted(challengers, key=lambda c: c.id, reverse=True)[0]
    comparison = {
        "champion": champion.version if champion else None,
        "challenger": cand.version,
        "champion_metrics": champion.metrics if champion else None,
        "challenger_metrics": cand.metrics,
    }
    # Conservative: never auto-approve
    rec = "retain_champion"
    if champion and cand.metrics and champion.metrics:
        c_auc = (cand.metrics or {}).get("auc")
        h_auc = (champion.metrics or {}).get("auc")
        if c_auc is not None and h_auc is not None and c_auc > h_auc + 0.02:
            rec = "manual_review_challenger_improved_auc"
        else:
            rec = "retain_champion_improvement_uncertain"
    report = m.PromotionReport(
        champion_model_id=champion.id if champion else None,
        challenger_model_id=cand.id,
        comparison=comparison,
        recommendation=rec,
        approved=False,
    )
    ctx.db.add(report)
    ctx.db.commit()
    ctx.metrics["promotion"] = {
        "recommendation": rec,
        "approved": False,
        "note": "Manual approval required; daily pipeline does not auto-promote",
    }


def stage_save_findings(ctx: PipelineContext) -> None:
    """Persist research findings with evidence metadata (deduped)."""
    for f in ctx.findings:
        upsert_finding(
            ctx.db,
            claim=f["claim"],
            topic="daily_pipeline",
            horizon=get_settings().default_horizon,
            sample_size=f.get("sample_size"),
            effect_size=f.get("effect_size"),
            data_cutoff=ctx.session_date,
            status=f.get("status", FindingStatus.EXPLORATORY),
        )
    promo = ctx.metrics.get("promotion", {})
    upsert_finding(
        ctx.db,
        claim=(
            f"Promotion recommendation: {promo.get('recommendation', 'n/a')}. "
            "No automatic promotion."
        ),
        topic="promotion",
        horizon=get_settings().default_horizon,
        data_cutoff=ctx.session_date,
        status=FindingStatus.EXPLORATORY,
    )
    ctx.db.commit()


def stage_generate_reports(ctx: PipelineContext) -> None:
    """Write plain-English artifact bundle."""
    settings = get_settings()
    out = Path(settings.local_storage_root) / "artifacts" / (
        ctx.run.run_key if ctx.run else "adhoc"
    )
    out.mkdir(parents=True, exist_ok=True)
    ctx.artifact_dir = out
    write_artifact_bundle(out, ctx)
    # Also store via object storage
    store = get_object_storage()
    for path in out.iterdir():
        if path.is_file():
            store.put_bytes(
                f"pipeline/{ctx.run.run_key}/{path.name}",
                path.read_bytes(),
            )


def stage_finalize(ctx: PipelineContext) -> None:
    """Finalise run status and release lock."""
    if not ctx.run:
        return
    ctx.run.finished_at = datetime.now(timezone.utc)
    ctx.run.error_summary = ctx.error_summary
    ctx.run.manifest = {
        "warnings": ctx.warnings,
        "metrics": ctx.metrics,
        "download": {
            k: v
            for k, v in ctx.download_stats.items()
            if not k.startswith("_")
        },
        "replay": ctx.replay_stats,
        "artifact_dir": str(ctx.artifact_dir) if ctx.artifact_dir else None,
    }
    if ctx.failed:
        ctx.run.status = PipelineRunStatus.FAILED
    elif ctx.warnings:
        ctx.run.status = PipelineRunStatus.PARTIAL
    else:
        ctx.run.status = PipelineRunStatus.SUCCESS
    ctx.db.commit()
    ctx.db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": 82451233})
    ctx.db.commit()
