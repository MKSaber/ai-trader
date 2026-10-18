"""Upload validation helpers — treat uploads as untrusted data."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".pdf", ".txt"}
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str) -> str:
    """Return a path-safe basename without directory components."""
    base = Path(name).name
    cleaned = SAFE_NAME_RE.sub("_", base).strip("._")
    return cleaned or "upload.bin"


def assert_allowed_extension(filename: str) -> str:
    """Validate extension; return lowercased suffix."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type {suffix!r}. "
            f"Allowed: {sorted(ALLOWED_EXTENSIONS)}"
        )
    return suffix


def assert_size_ok(size_bytes: int, max_mb: int) -> None:
    """Reject oversized uploads."""
    limit = max_mb * 1024 * 1024
    if size_bytes > limit:
        raise ValueError(f"File exceeds {max_mb} MB limit")


def sha256_bytes(data: bytes) -> str:
    """Compute SHA-256 hex digest."""
    return hashlib.sha256(data).hexdigest()
