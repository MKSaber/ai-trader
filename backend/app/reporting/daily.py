"""Plain-English daily report and machine-readable exports."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.pipeline.orchestrator import PipelineContext


def write_artifact_bundle(out_dir: Path, ctx: PipelineContext) -> None:
    """Write DAILY_REPORT.md, SUMMARY.txt, csv/json exports."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_key": ctx.run.run_key if ctx.run else None,
        "session_date": ctx.session_date.isoformat() if ctx.session_date else None,
        "dry_run": ctx.dry_run,
        "offline": ctx.offline,
        "status": ctx.run.status if ctx.run else None,
        "warnings": ctx.warnings,
        "failed": ctx.failed,
        "error_summary": ctx.error_summary,
    }
    (out_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    (out_dir / "metrics.json").write_text(
        json.dumps(ctx.metrics, indent=2, default=str), encoding="utf-8"
    )

    # signals / closed trades from DB
    _write_signals_csv(out_dir, ctx)
    _write_trades_csv(out_dir, ctx)

    warnings_path = out_dir / "data_quality_warnings.txt"
    warnings_path.write_text(
        "\n".join(ctx.warnings) if ctx.warnings else "None",
        encoding="utf-8",
    )

    report = _build_daily_report_md(ctx)
    (out_dir / "DAILY_REPORT.md").write_text(report, encoding="utf-8")
    (out_dir / "SUMMARY.txt").write_text(_build_summary(ctx), encoding="utf-8")
    (out_dir / "sanitised.log").write_text(
        f"run={manifest['run_key']} status={manifest['status']}\n"
        f"error={ctx.error_summary or 'none'}\n",
        encoding="utf-8",
    )


def _build_summary(ctx: PipelineContext) -> str:
    paper = (ctx.metrics.get("paper") or {}).get("trades") or {}
    promo = ctx.metrics.get("promotion") or {}
    lines = [
        "LSE Pattern Lab — daily summary (nontechnical)",
        f"Session: {ctx.session_date}",
        f"Data offline/demo: {ctx.offline}",
        f"Warnings: {len(ctx.warnings)}",
        f"Paper trades closed: {paper.get('n', 0)}",
        f"Net P&L (paper): {paper.get('net_total', 'n/a')}",
        f"Model promotion: {promo.get('recommendation', 'n/a')} "
        "(manual approval required)",
    ]
    if ctx.failed:
        lines.append(f"Run FAILED: {ctx.error_summary}")
    else:
        lines.append("Run completed without hard failure (check warnings).")
    lines.append(
        "This is research output. It does not promise profits or live trading."
    )
    return "\n".join(lines) + "\n"


def _build_daily_report_md(ctx: PipelineContext) -> str:
    dl = {k: v for k, v in ctx.download_stats.items() if not str(k).startswith("_")}
    paper = ctx.metrics.get("paper") or {}
    trades = paper.get("trades") or {}
    promo = ctx.metrics.get("promotion") or {}
    retrain = ctx.metrics.get("retrain")

    setups_note = "No qualified setups"
    if paper.get("setups"):
        setups_note = f"{paper.get('setups')} setups generated (see signals.csv)"

    parts = [
        "# LSE Pattern Lab — Daily Report",
        "",
        f"- **Run:** `{ctx.run.run_key if ctx.run else 'n/a'}`",
        f"- **Session date:** {ctx.session_date}",
        f"- **Data cutoff:** provider watermark / session end",
        f"- **Offline/demo:** {ctx.offline}",
        f"- **Dry run:** {ctx.dry_run}",
        "",
        "## 1. Data arrival and completeness",
        "",
        f"Provider: **{dl.get('provider', 'n/a')}** — {dl.get('provider_health', '')}",
        "",
        "```json",
        json.dumps(dl, indent=2, default=str),
        "```",
        "",
        "Yahoo Finance via yfinance is a prototype feed. Intraday history is "
        "typically limited to about 60 days. This is not a guaranteed production "
        "feed and does not by itself establish a trading edge.",
        "",
        "## 2. Prior forecasts and paper trades",
        "",
        f"Resolved predictions: {ctx.metrics.get('resolved_predictions')}",
        "",
        f"Replay: {json.dumps(paper, default=str)}",
        "",
        "## 3. Gross, costs, and net",
        "",
        f"- Gross total: {trades.get('gross_total', 'n/a')}",
        f"- Costs total: {trades.get('costs_total', 'n/a')}",
        f"- Net total: {trades.get('net_total', 'n/a')}",
        "",
        "Facts above are paper-simulated with documented assumptions. "
        "They are not broker statements.",
        "",
        "## 4. Patterns that gained or lost support",
        "",
    ]
    for f in ctx.findings:
        parts.append(f"- {f.get('claim')}")
    if not ctx.findings:
        parts.append("- No new pattern claims this run.")
    parts.extend(
        [
            "",
            "## 5. Model changes",
            "",
            f"Retrain result: `{json.dumps(retrain, default=str)}`",
            "",
            "If retrain was skipped, the champion formula did not change today. "
            "Daily ingestion does not require daily retraining.",
            "",
            "## 6. Challenger vs champion",
            "",
            f"Recommendation: **{promo.get('recommendation', 'n/a')}**",
            f"Auto-approved: **{promo.get('approved', False)}**",
            "",
            str(promo.get("note", "Manual approval required.")),
            "",
            "## 7. Candidate setups",
            "",
            setups_note,
            "",
            "## 8. Failures, uncertainty, human action",
            "",
            f"- Failed: {ctx.failed}",
            f"- Error: {ctx.error_summary or 'none'}",
            f"- Warnings ({len(ctx.warnings)}):",
        ]
    )
    for w in ctx.warnings:
        parts.append(f"  - {w}")
    parts.extend(
        [
            "",
            "### Required human action",
            "",
            "- Review promotion recommendation before changing the champion.",
            "- Review data-quality warnings.",
            "- Do not treat exploratory findings as established truth.",
            "",
            "---",
            "",
            "*Hypotheses are labelled exploratory. Synthetic/offline data cannot "
            "establish profitability.*",
            "",
        ]
    )
    return "\n".join(parts)


def _write_signals_csv(out_dir: Path, ctx: PipelineContext) -> None:
    from sqlalchemy import select

    from app.db import models as mm

    rows = ctx.db.scalars(select(mm.IntradaySetup).limit(5000)).all()
    path = out_dir / "signals.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "id",
                "instrument_id",
                "signal_ts",
                "model_version",
                "no_trade",
                "entry_low",
                "entry_high",
                "stop_loss",
                "take_profit",
                "expected_net_return",
                "outcome",
                "reason",
            ],
        )
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "id": r.id,
                    "instrument_id": r.instrument_id,
                    "signal_ts": r.signal_ts.isoformat() if r.signal_ts else "",
                    "model_version": r.model_version,
                    "no_trade": r.no_trade,
                    "entry_low": r.entry_low,
                    "entry_high": r.entry_high,
                    "stop_loss": r.stop_loss,
                    "take_profit": r.take_profit,
                    "expected_net_return": r.expected_net_return,
                    "outcome": r.outcome,
                    "reason": r.reason,
                }
            )


def _write_trades_csv(out_dir: Path, ctx: PipelineContext) -> None:
    from sqlalchemy import select

    from app.db import models as mm

    rows = ctx.db.scalars(
        select(mm.PaperPosition).where(mm.PaperPosition.closed_at.is_not(None))
    ).all()
    path = out_dir / "closed_trades.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "id",
                "setup_id",
                "instrument_id",
                "opened_at",
                "closed_at",
                "entry_price",
                "exit_price",
                "gross_pnl",
                "costs",
                "net_pnl",
                "exit_reason",
                "ambiguity_flag",
            ],
        )
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "id": r.id,
                    "setup_id": r.setup_id,
                    "instrument_id": r.instrument_id,
                    "opened_at": r.opened_at.isoformat() if r.opened_at else "",
                    "closed_at": r.closed_at.isoformat() if r.closed_at else "",
                    "entry_price": r.entry_price,
                    "exit_price": r.exit_price,
                    "gross_pnl": r.gross_pnl,
                    "costs": r.costs,
                    "net_pnl": r.net_pnl,
                    "exit_reason": r.exit_reason,
                    "ambiguity_flag": r.ambiguity_flag,
                }
            )
