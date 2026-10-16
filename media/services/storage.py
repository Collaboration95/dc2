"""Only Media source operations and output reads; never output writes/deletes."""

import hashlib
from datetime import UTC, datetime, timedelta
from tempfile import TemporaryFile
from typing import Annotated

from fastapi import Depends, Request
from minio import Minio
from minio.credentials import StaticProvider
from minio.datatypes import PostPolicy
from minio.deleteobjects import DeleteObject
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

    async def direct_upload_grant(self, reservation):
        def grant():
            policy = PostPolicy(reservation.bucket, reservation.expires_at)
            policy.add_equals_condition("key", reservation.key)
            policy.add_equals_condition("Content-Type", reservation.content_type)
            policy.add_content_length_range_condition(1, reservation.size_bytes)
            fields = self.public.presigned_post_policy(policy)
            fields.update({"key": reservation.key, "Content-Type": reservation.content_type})
            scheme = "https" if self.settings.minio_public_use_ssl else "http"
            return {
                "method": "POST",
                "url": f"{scheme}://{self.settings.minio_public_endpoint}/{reservation.bucket}",
                "fields": fields,
            }

        try:
            return await run_in_threadpool(grant)
        except Exception:
            raise MediaError(503, "storage signing unavailable") from None

    async def verify_direct_upload(self, reservation, *, check_content=True):
        def verify():
            from media.services.media_type import SNIFF_LENGTH, sniff_video_type

            stat = self.internal.stat_object(reservation.bucket, reservation.key)
            version = stat.version_id
            if not version or version == "null":
                raise MediaError(503, "source versioning required")
            if stat.size != reservation.size_bytes or stat.size > MAX_FILE_SIZE:
                raise MediaError(422, "source size does not match reservation")
            if stat.content_type != reservation.content_type:
                raise MediaError(415, "source content type does not match reservation")
            response = self.internal.get_object(
                reservation.bucket, reservation.key, version_id=version
            )
            try:
                digest, size, prefix = hashlib.sha256(), 0, b""
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > reservation.size_bytes:
                        raise MediaError(422, "source size does not match reservation")
                    prefix = (prefix + chunk)[:SNIFF_LENGTH]
                    digest.update(chunk)
                if size != reservation.size_bytes or digest.hexdigest() != reservation.sha256:
                    raise MediaError(422, "source checksum does not match reservation")
                if check_content and sniff_video_type(prefix) != reservation.content_type:
                    raise MediaError(415, "source bytes do not match content type")
                return version
            finally:
                response.close()
                response.release_conn()

        try:
            return await run_in_threadpool(verify)
        except MediaError:
            raise
        except Exception:
            raise MediaError(503, "source object unavailable; retry finalization") from None

    async def remove_source_versions(self, bucket, key, *, preserve_version=None):
        """Delete every stored version and delete marker of exactly ``key``.

        A bare DELETE on a versioned bucket only adds a delete marker and leaves the bytes
        stored, so cleanup must name each version. Raises when any deletion is refused.
        """

        def remove():
            objects = self.internal.list_objects(
                bucket, prefix=key, recursive=True, include_version=True
            )
            deletes = (
                DeleteObject(obj.object_name, obj.version_id)
                for obj in objects
                if obj.object_name == key and obj.version_id != preserve_version
            )
            if list(self.internal.remove_objects(bucket, deletes)):
                raise MediaError(503, "source cleanup deferred")

        await run_in_threadpool(remove)

    async def delete_direct_upload(self, reservation, *, preserve_version=None):
        await self.remove_source_versions(
            reservation.bucket, reservation.key, preserve_version=preserve_version
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
        # Version-aware so a failed edit's copied bytes are actually released.
        await self.remove_source_versions(self.settings.minio_source_bucket, key)

    def _sign(self, key, *, output=False, inline=False, version_id=None):
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
                version_id=version_id,
            )
            return url, signed_at + timedelta(seconds=seconds)
        except Exception:
            raise MediaError(503, "storage signing unavailable") from None

    async def source_grant(self, key, version_id=None):
        # Pass the pinned VersionId whenever one exists; an unversioned GET of a staging
        # key returns the newest object, which a replayed upload grant could have replaced.
        return await run_in_threadpool(self._sign, key, version_id=version_id)

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
