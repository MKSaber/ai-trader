"""Upload sanitisation tests."""

import pytest

from app.core.upload_security import (
    assert_allowed_extension,
    assert_size_ok,
    sanitize_filename,
    sha256_bytes,
)


def test_sanitize_strips_path() -> None:
    """Path components removed."""
    assert sanitize_filename("../../etc/passwd.csv") == "passwd.csv"


def test_reject_exe() -> None:
    """Executable extensions rejected."""
    with pytest.raises(ValueError):
        assert_allowed_extension("evil.exe")


def test_size_limit() -> None:
    """Oversized upload rejected."""
    with pytest.raises(ValueError):
        assert_size_ok(30 * 1024 * 1024, max_mb=25)


def test_hash_stable() -> None:
    """SHA-256 deterministic."""
    assert sha256_bytes(b"abc") == sha256_bytes(b"abc")
