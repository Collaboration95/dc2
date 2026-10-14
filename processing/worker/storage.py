"""Only acknowledged output PUT; no HEAD/Get or Media storage credentials."""

import asyncio
import hashlib
import os

import urllib3
from minio import Minio

from processing.storage_credentials import credential_provider


class _HashingReader:
    def __init__(self, handle):
        self.handle = handle
        self.checksum = hashlib.sha256()
        self.size = 0

    def read(self, size=-1):
        chunk = self.handle.read(size)
        self.checksum.update(chunk)
        self.size += len(chunk)
        return chunk


class OutputStore:
    def __init__(self, settings):
        self.bucket = settings.minio_output_bucket
        self.client = Minio(
            settings.minio_endpoint,
            secure=settings.minio_use_ssl,
            region=settings.minio_region,
            credentials=credential_provider(settings),
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
        return await asyncio.to_thread(self._put, key, path, media_type, kind)

    def _put(self, key, path, media_type, kind):
        with path.open("rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            if size <= 0:
                raise ValueError("output upload was not acknowledged")
            # Hash the exact SDK input while it reads each part, avoiding a separate
            # full-file pass. MinIO retains its existing bounded multipart buffering.
            reader = _HashingReader(handle)
            result = self.client.put_object(
                self.bucket,
                key,
                reader,
                size,
                content_type=media_type,
                num_parallel_uploads=1,
            )
            if not result.etag or reader.size != size or handle.read(1):
                raise ValueError("output upload was not acknowledged")
            checksum = reader.checksum.hexdigest()
        return {
            "kind": kind,
            "object_key": key,
            "media_type": media_type,
            "size_bytes": size,
            "sha256": checksum,
        }
