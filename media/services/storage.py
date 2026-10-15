"""Only Media source operations and output reads; never output writes/deletes."""

import hashlib
from datetime import UTC, datetime, timedelta
from tempfile import TemporaryFile
from typing import Annotated

from fastapi import Depends, Request
from minio import Minio
from minio.credentials import StaticProvider
from starlette.concurrency import run_in_threadpool
from urllib3 import PoolManager, Retry, Timeout

from media.config import Settings, get_settings
from media.errors import MediaError
from media.storage_credentials import credential_provider

MAX_FILE_SIZE = 100 * 1024 * 1024


class Storage:
    def __init__(self, settings: Settings, *, clock=None):
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(UTC))
        self.provider = credential_provider(settings)
        options = {"credentials": self.provider, "region": settings.minio_region}
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

    def _sign(self, key, *, output=False, inline=False):
        try:
            credential = self.provider.retrieve() if self.provider else None
            signed_at = self.clock().replace(microsecond=0)
            seconds = self.settings.signed_url_ttl_seconds
            if credential and credential.expiration:
                seconds = min(
                    seconds,
                    int((credential.expiration.replace(tzinfo=UTC) - signed_at).total_seconds())
                    - 10,
                )
                if seconds < 30:
                    raise ValueError("Insufficient signing lifetime")
            # One disposable signer pins exactly the snapshot used to compute TTL.
            signer = Minio(
                self.settings.minio_public_endpoint if output else self.settings.minio_endpoint,
                secure=(
                    self.settings.minio_public_use_ssl if output else self.settings.minio_use_ssl
                ),
                region=self.settings.minio_region,
                credentials=(
                    StaticProvider(
                        credential.access_key, credential.secret_key, credential.session_token
                    )
                    if credential
                    else None
                ),
            )
            url = signer.get_presigned_url(
                "GET",
                self.settings.minio_output_bucket if output else self.settings.minio_source_bucket,
                key,
                expires=timedelta(seconds=seconds),
                request_date=signed_at,
                response_headers={"response-content-disposition": "inline"} if inline else None,
            )
            return url, signed_at + timedelta(seconds=seconds)
        except Exception:
            raise MediaError(503, "storage signing unavailable") from None

    async def source_grant(self, key):
        return await run_in_threadpool(self._sign, key)

    async def sign_output(self, key, *, inline=False):
        url, _ = await run_in_threadpool(self._sign, key, output=True, inline=inline)
        return url

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
