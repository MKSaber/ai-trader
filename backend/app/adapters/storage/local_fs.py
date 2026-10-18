"""Local filesystem object storage for Docker development."""

from __future__ import annotations

from pathlib import Path


class LocalFilesystemStorage:
    """Store blobs under a configured root directory."""

    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, key: str, data: bytes, content_type: str = "") -> str:
        """Write bytes to root/key."""
        del content_type  # unused locally
        path = self._safe_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def get_bytes(self, key: str) -> bytes:
        """Read bytes from root/key."""
        return self._safe_path(key).read_bytes()

    def exists(self, key: str) -> bool:
        """Check existence."""
        return self._safe_path(key).exists()

    def uri(self, key: str) -> str:
        """file:// URI."""
        return self._safe_path(key).resolve().as_uri()

    def _safe_path(self, key: str) -> Path:
        """Prevent path traversal outside root."""
        cleaned = key.lstrip("/").replace("..", "_")
        path = (self._root / cleaned).resolve()
        if not str(path).startswith(str(self._root.resolve())):
            raise ValueError("Invalid storage key")
        return path
