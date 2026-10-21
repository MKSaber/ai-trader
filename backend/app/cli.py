"""CLI entry point for daily research runs (no dashboard required)."""

from __future__ import annotations

from datetime import date
from typing import Optional

import typer
from rich.console import Console

from app.db.session import SessionLocal
from app.pipeline.orchestrator import run_daily_pipeline

cli = typer.Typer(
    name="lse-lab",
    help="LSE Pattern Lab research CLI — not automatic trading.",
    add_completion=False,
)
console = Console()


@cli.command("daily-run")
def daily_run(
    session: Optional[str] = typer.Option(
        None,
        "--session",
        help="Target Europe/London market session YYYY-MM-DD",
    ),
    catchup_from: Optional[str] = typer.Option(
        None, "--from", help="Catch-up range start YYYY-MM-DD"
    ),
    catchup_to: Optional[str] = typer.Option(
        None, "--to", help="Catch-up range end YYYY-MM-DD"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Skip downloads/writes where noted"),
    offline: bool = typer.Option(
        False,
        "--offline",
        help="Explicit offline/demo mode using fixture provider only",
    ),
    symbols: str = typer.Option(
        "VOD.L,BP.L,HSBA.L,GSK.L,AZN.L",
        "--symbols",
        help="Comma-separated Yahoo LSE symbols",
    ),
) -> None:
    """Run the full daily research pipeline."""
    console.print("[bold]LSE Pattern Lab — daily-run[/bold]")
    console.print(
        "Research pipeline only. No broker orders. No automatic champion promotion."
    )
    # Guard against Click/Typer bool-flag regressions that yield str/None.
    dry_run_b = dry_run is True or (
        isinstance(dry_run, str) and dry_run.strip().lower() in {"1", "true", "yes"}
    )
    offline_b = offline is True or (
        isinstance(offline, str) and offline.strip().lower() in {"1", "true", "yes"}
    )
    db = SessionLocal()
    try:
        result = run_daily_pipeline(
            db,
            session_date=date.fromisoformat(session) if session else None,
            catchup_from=date.fromisoformat(catchup_from) if catchup_from else None,
            catchup_to=date.fromisoformat(catchup_to) if catchup_to else None,
            dry_run=dry_run_b,
            offline=offline_b,
            symbols=[s.strip() for s in symbols.split(",") if s.strip()],
        )
        console.print(result)
        if result.get("status") == "failed":
            raise typer.Exit(code=1)
    finally:
        db.close()


@cli.command("version")
def version() -> None:
    """Print package version."""
    console.print("lse-pattern-lab 0.1.0")


# Typer app alias used by setuptools script and `python -m app.cli`
app = cli


def main() -> None:
    """Module entry."""
    cli()


if __name__ == "__main__":
    main()
