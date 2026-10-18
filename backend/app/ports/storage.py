"""Object storage port for raw files, snapshots and model artifacts."""

from __future__ import annotations

from typing import Protocol


class ObjectStorage(Protocol):
    """Persistent blob storage — not ephemeral runner disk."""

    def put_bytes(self, key: str, data: bytes, content_type: str = "") -> str:
        """Store bytes; return storage URI/key."""

    def get_bytes(self, key: str) -> bytes:
        """Load bytes by key."""

    def exists(self, key: str) -> bool:
        """Return True if key exists."""

    def uri(self, key: str) -> str:
        """Return a displayable URI for the key."""
