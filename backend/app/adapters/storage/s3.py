"""S3-compatible object storage adapter for CI / production persistence."""

from __future__ import annotations

import boto3
from botocore.client import BaseClient


class S3CompatibleStorage:
    """Persist blobs in an S3-compatible bucket."""

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str = "auto",
    ) -> None:
        if not bucket:
            raise ValueError("S3_BUCKET is required for s3 storage backend")
        self._bucket = bucket
        kwargs: dict = {"region_name": region}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if access_key and secret_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key
        self._client: BaseClient = boto3.client("s3", **kwargs)

    def put_bytes(self, key: str, data: bytes, content_type: str = "") -> str:
        """Upload object."""
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=data, **extra
        )
        return self.uri(key)

    def get_bytes(self, key: str) -> bytes:
        """Download object."""
        obj = self._client.get_object(Bucket=self._bucket, Key=key)
        return obj["Body"].read()

    def exists(self, key: str) -> bool:
        """Head object."""
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False

    def uri(self, key: str) -> str:
        """s3:// URI."""
        return f"s3://{self._bucket}/{key}"
