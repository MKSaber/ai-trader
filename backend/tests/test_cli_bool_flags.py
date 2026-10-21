"""CLI bool flags must be real bools (Click 8.5 + Typer 0.12 regression)."""

from __future__ import annotations

from typer.testing import CliRunner

from app.cli import cli
from app.pipeline.orchestrator import _as_bool


def test_as_bool_coerces_click_string_false() -> None:
    assert _as_bool(False) is False
    assert _as_bool(True) is True
    assert _as_bool("False") is False
    assert _as_bool("false") is False
    assert _as_bool("True") is True
    assert _as_bool(None) is False


def test_daily_run_bool_defaults_are_bools(monkeypatch) -> None:
    """Invoke CLI without flags; dry_run/offline must reach pipeline as bools."""
    captured: dict = {}

    def fake_pipeline(db, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return {"status": "success", "run_key": "t"}

    monkeypatch.setattr("app.cli.run_daily_pipeline", fake_pipeline)
    monkeypatch.setattr("app.cli.SessionLocal", lambda: type("S", (), {"close": lambda self: None})())

    result = CliRunner().invoke(cli, ["daily-run"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert captured["dry_run"] is False
    assert captured["offline"] is False
    assert isinstance(captured["dry_run"], bool)
    assert isinstance(captured["offline"], bool)


def test_daily_run_flags_are_true(monkeypatch) -> None:
    captured: dict = {}

    def fake_pipeline(db, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return {"status": "success", "run_key": "t"}

    monkeypatch.setattr("app.cli.run_daily_pipeline", fake_pipeline)
    monkeypatch.setattr("app.cli.SessionLocal", lambda: type("S", (), {"close": lambda self: None})())

    result = CliRunner().invoke(cli, ["daily-run", "--offline", "--dry-run"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert captured["dry_run"] is True
    assert captured["offline"] is True
