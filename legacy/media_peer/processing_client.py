from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, Request
from pydantic import TypeAdapter, ValidationError

from legacy.media_peer.config import LegacyMediaSettings
from legacy.media_peer.errors import PeerError
from legacy.media_peer.schemas import ProcessingJob
from media.config import get_settings


class ProcessingClient:
    def __init__(self, client: httpx.AsyncClient, token: str):
        self.client = client
        self.token = token

    async def request(self, method: str, path: str, owner_id: UUID, **kwargs):
        if not self.token:
            raise PeerError()
        try:
            response = await self.client.request(
                method,
                path,
                headers={"Authorization": "Bearer " + self.token, "X-Owner-Id": str(owner_id)},
                **kwargs,
            )
        except (httpx.HTTPError, OSError, TimeoutError) as exc:
            raise PeerError() from exc
        if not 200 <= response.status_code < 300:
            raise PeerError(
                response.status_code if response.status_code in (404, 409, 410) else 503
            )
        return response

    def decode(self, response, owner_id: UUID) -> ProcessingJob:
        try:
            job = ProcessingJob.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise PeerError() from exc
        if job.owner_id != owner_id:
            raise PeerError()
        return job

    async def submit(self, owner_id: UUID, payload: dict) -> ProcessingJob:
        response = await self.request("POST", "/internal/v1/jobs", owner_id, json=payload)
        job = self.decode(response, owner_id)
        if (
            str(job.asset_id) != payload["asset_id"]
            or job.source.model_dump(mode="json") != (payload["source"])
        ):
            raise PeerError()
        return job

    async def read(self, owner_id: UUID, job_id: UUID) -> ProcessingJob:
        job = self.decode(
            await self.request("GET", f"/internal/v1/jobs/{job_id}", owner_id), owner_id
        )
        if job.job_id != job_id:
            raise PeerError()
        return job

    async def batch(self, owner_id: UUID, asset_ids: list[UUID]) -> list[ProcessingJob]:
        if not asset_ids:
            return []
        response = await self.request(
            "GET",
            "/internal/v1/jobs",
            owner_id,
            params={"asset_ids": ",".join(map(str, asset_ids))},
        )
        try:
            jobs = TypeAdapter(list[ProcessingJob]).validate_python(response.json())
        except (ValueError, ValidationError) as exc:
            raise PeerError() from exc
        if any(j.owner_id != owner_id or j.asset_id not in asset_ids for j in jobs) or len(
            {j.asset_id for j in jobs}
        ) != len(jobs):
            raise PeerError()
        return jobs

    async def retry(self, owner_id: UUID, job_id: UUID, retry_id: UUID) -> ProcessingJob:
        response = await self.request(
            "POST",
            f"/internal/v1/jobs/{job_id}/retry",
            owner_id,
            json={"retry_request_id": str(retry_id)},
        )
        job = self.decode(response, owner_id)
        if job.job_id != job_id:
            raise PeerError()
        return job

    async def cancel(self, owner_id: UUID, asset_id: UUID) -> None:
        await self.request("DELETE", f"/internal/v1/assets/{asset_id}/job", owner_id)


def get_processing_client(
    request: Request, settings: Annotated[LegacyMediaSettings, Depends(get_settings)]
) -> ProcessingClient:
    if getattr(request.app.state, "http_client", None) is None:
        request.app.state.http_client = httpx.AsyncClient(
            base_url=settings.processing_url,
            timeout=settings.processing_timeout_seconds,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=50),
        )
    return ProcessingClient(
        request.app.state.http_client, settings.processing_service_token.get_secret_value()
    )


Peer = Annotated[ProcessingClient, Depends(get_processing_client)]
