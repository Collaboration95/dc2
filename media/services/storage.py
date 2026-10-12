"""Only Media source operations and output reads; never output writes/deletes."""

import hashlib
from datetime import UTC, datetime, timedelta
from tempfile import TemporaryFile
from typing import Annotated

from fastapi import Depends, Request
from minio import Minio
from starlette.concurrency import run_in_threadpool
from urllib3 import PoolManager, Retry, Timeout

from media.config import Settings, get_settings
from media.errors import MediaError

MAX_FILE_SIZE = 100 * 1024 * 1024


class Storage:
    def __init__(self, settings: Settings):
        self.settings = settings
        options = {
            "access_key": settings.minio_access_key,
            "secret_key": settings.minio_secret_key.get_secret_value(),
            "region": settings.minio_region,
        }
        transport = PoolManager(
            num_pools=10,
            maxsize=20,
            timeout=Timeout(connect=2, read=10),
            retries=Retry(total=1, backoff_factor=0.2),
        )
        self.internal = Minio(
            settings.minio_endpoint, secure=settings.minio_use_ssl, http_client=transport, **options
        )
        self.public = Minio(
            settings.minio_public_endpoint, secure=settings.minio_public_use_ssl, **options
        )

    async def put_source(self, key, stream, size, media_type):
        await run_in_threadpool(
            self.internal.put_object,
            self.settings.minio_source_bucket,
            key,
            stream,
            size,
            content_type=media_type,
        )

    async def delete_source(self, key):
        await run_in_threadpool(self.internal.remove_object, self.settings.minio_source_bucket, key)

    async def source_grant(self, key):
        ttl = timedelta(seconds=self.settings.signed_url_ttl_seconds)
        # Explicit region means signing is local and does not need bucket discovery.
        url = await run_in_threadpool(
            self.internal.presigned_get_object, self.settings.minio_source_bucket, key, expires=ttl
        )
        return url, datetime.now(UTC) + ttl

    async def sign_output(self, key, *, inline=False):
        headers = {"response-content-disposition": "inline"} if inline else None
        return await run_in_threadpool(
            self.public.presigned_get_object,
            self.settings.minio_output_bucket,
            key,
            expires=timedelta(seconds=self.settings.signed_url_ttl_seconds),
            response_headers=headers,
        )

    async def read_playlist(self, key):
        def read():
            response = self.internal.get_object(self.settings.minio_output_bucket, key)
            try:
                body = response.read(1024 * 1024 + 1)
                if len(body) > 1024 * 1024:
                    raise MediaError(503, "playlist unavailable")
                return body
            finally:
                response.close()
                response.release_conn()

        return await run_in_threadpool(read)

    async def copy_output_source(self, output, key):
        # MM outputGet/sourcePut policy permits this bounded streaming copy. S3
        # server-side copy would not verify the immutable content digest locally.
        def copy():
            response = self.internal.get_object(
                self.settings.minio_output_bucket, output.object_key
            )
            try:
                with TemporaryFile() as stream:
                    digest = hashlib.sha256()
                    size = 0
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if output.size_bytes is not None and size > output.size_bytes:
                            raise MediaError(503, "output verification failed")
                        digest.update(chunk)
                        stream.write(chunk)
                    if not size or (output.size_bytes is not None and size != output.size_bytes):
                        raise MediaError(503, "output verification failed")
                    sha256 = digest.hexdigest()
                    if output.sha256 is not None and sha256 != output.sha256:
                        raise MediaError(503, "output verification failed")
                    stream.seek(0)
                    self.internal.put_object(
                        self.settings.minio_source_bucket,
                        key,
                        stream,
                        size,
                        content_type=output.media_type,
                    )
                    return size, sha256
            finally:
                response.close()
                response.release_conn()

        return await run_in_threadpool(copy)


def get_storage(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> Storage:
    if getattr(request.app.state, "storage", None) is None:
        request.app.state.storage = Storage(settings)
    return request.app.state.storage


Store = Annotated[Storage, Depends(get_storage)]
