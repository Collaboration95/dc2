"""Only acknowledged output PUT; no HEAD/Get or Media storage credentials."""

import asyncio
import hashlib
from pathlib import Path

import urllib3
from minio import Minio


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


class OutputStore:
    def __init__(self, settings):
        self.bucket = settings.minio_output_bucket
        self.client = Minio(
            settings.minio_endpoint,
            secure=settings.minio_use_ssl,
            region=settings.minio_region,
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            http_client=urllib3.PoolManager(
                timeout=urllib3.Timeout(
                    connect=settings.http_timeout_seconds, read=settings.http_timeout_seconds
                ),
                retries=False,
            ),
        )

    async def put(self, key, path, media_type, kind):
        # Cancellation may leave a PUT thread finishing later. The retained cleanup
        # intent re-scans the attempt prefix; no stale thread can publish in SQL.
        size = path.stat().st_size
        checksum = await asyncio.to_thread(digest, path)
        result = await asyncio.to_thread(
            self.client.fput_object,
            self.bucket,
            key,
            str(path),
            content_type=media_type,
            num_parallel_uploads=1,
        )
        if not result.etag or size <= 0:
            raise ValueError("output upload was not acknowledged")
        return {
            "kind": kind,
            "object_key": key,
            "media_type": media_type,
            "size_bytes": size,
            "sha256": checksum,
        }
