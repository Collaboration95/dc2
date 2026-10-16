"""Native read of the accepted immutable source, never a Media HTTP callback."""

import asyncio
import hashlib

import urllib3
from minio import Minio

from processing.storage_credentials import credential_provider


class SourceStore:
    def __init__(self, settings, *, client=None):
        self.client = client or Minio(
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

    async def download(self, _client, work, _settings, path):
        # SQL claim validates this descriptor against accepted state before this call.
        await asyncio.to_thread(self._download, work.source, path)

    def _download(self, source, path):
        required = {"bucket", "key", "version_id", "sha256", "size_bytes", "content_type"}
        if (
            not required.issubset(source)
            or not source["version_id"]
            or source["version_id"] == "null"
        ):
            raise ValueError("An immutable accepted source version is required")
        if not 0 < source["size_bytes"] <= 100 * 1024 * 1024:
            raise ValueError("Invalid accepted source size")
        response = self.client.get_object(
            source["bucket"], source["key"], version_id=source["version_id"]
        )
        try:
            if response.headers.get("x-amz-version-id") != source["version_id"]:
                raise ValueError("Source version did not match accepted state")
            digest, size = hashlib.sha256(), 0
            with path.open("wb") as handle:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > source["size_bytes"]:
                        raise ValueError("Source exceeds accepted size")
                    digest.update(chunk)
                    handle.write(chunk)
            if size != source["size_bytes"] or digest.hexdigest() != source["sha256"]:
                raise ValueError("Source digest or size did not match accepted state")
        finally:
            response.close()
            response.release_conn()
