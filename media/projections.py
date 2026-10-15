"""Version-fenced result application and local public read projection.

``apply_result`` runs inside media.messaging.consume_result's transaction. The
inbox and projection commit together before the SQS adapter acknowledges delivery.
No function in this module opens a Processing HTTP or database connection.
"""

from pathlib import PurePosixPath
from uuid import UUID

from pydantic import BaseModel

from media.errors import MediaError
from media.models import now
from media.projection_models import DerivedSource, ProcessingProjection
from media.repositories.assets import fingerprint, get_asset
from media.schemas.peer import Output
from media.schemas.public import PublicJob


class ProjectedJob(BaseModel):
    job_id: UUID
    status: str
    outputs: list[Output]
    error: str | None = None


def _dict(envelope):
    if hasattr(envelope, "to_dict"):
        return envelope.to_dict()
    if hasattr(envelope, "model_dump"):
        return envelope.model_dump(mode="json")
    return envelope


def validate_transition(current, event):
    """Return False for stale/replayed state; reject equivocation and bad fences."""
    payload = event["payload"]
    version = event["state_version"]
    number = payload["attempt_number"]
    attempt_id = UUID(event["attempt_id"]) if event["attempt_id"] else None
    if current is None:
        return True
    if version < current.state_version:
        return False
    # Message identity is checked by the durable inbox; also protect the domain
    # version from two distinct message IDs claiming different state.
    digest = fingerprint({k: v for k, v in event.items() if k != "message_id"})
    if version == current.state_version:
        if digest != current.result_hash:
            raise MediaError(409, "conflicting result state version")
        return False
    if number < current.attempt_number:
        return False
    if number == current.attempt_number:
        if attempt_id != current.attempt_id:
            raise MediaError(409, "conflicting result attempt")
        if current.status in {"done", "failed", "cancelled"}:
            raise MediaError(409, "terminal attempt cannot change")
        if current.status == "processing" and payload["status"] == "queued":
            raise MediaError(409, "attempt state cannot regress")
    elif current.status in {"done", "cancelled"}:
        raise MediaError(409, "completed or cancelled job cannot restart")
    return True


async def apply_result(session, envelope):
    event = _dict(envelope)
    if event.get("schema_version") != 1 or event.get("kind") != "result":
        raise MediaError(422, "invalid result envelope")
    # Canonical validation is applied here as well as by delivery; callback use
    # cannot bypass schema validation.
    from contracts.v1 import Envelope

    event = Envelope.from_dict(event).to_dict()
    asset = await get_asset(
        session,
        UUID(event["asset_id"]),
        UUID(event["owner_id"]),
        include_deleted=True,
        lock=True,
    )
    if asset.deleted_at:
        return False  # Durable tombstone dominates every result, including late submit.
    if not event["job_id"] or not event["source"]:
        raise MediaError(422, "result requires job and immutable source")
    job_id = UUID(event["job_id"])
    if asset.processing_job_id and asset.processing_job_id != job_id:
        raise MediaError(409, "result belongs to another Processing job")
    # Accepted immutable descriptor is Media authority, not a claim from a queue.
    source = await source_for_asset(session, asset)
    if event["source"] != source:
        raise MediaError(409, "result source differs from accepted source")
    payload = event["payload"]
    status = payload.get("status")
    number = payload.get("attempt_number")
    if status not in {"queued", "processing", "done", "failed", "cancelled"}:
        raise MediaError(422, "invalid result status")
    if type(number) is not int or number < 0:
        raise MediaError(422, "invalid attempt number")
    if number > 0 and not event["attempt_id"]:
        raise MediaError(422, "result requires attempt identity")
    outputs = [Output.model_validate(o).model_dump(mode="json") for o in payload.get("outputs", [])]
    if status != "done" and outputs:
        raise MediaError(422, "unfinished job cannot publish outputs")
    if status == "done" and len([o for o in outputs if o["kind"] == "primary"]) != 1:
        raise MediaError(422, "completed job requires one primary output")
    # Prevent signing or copying arbitrary objects, even from a malformed producer.
    prefix = f"jobs/{job_id}/attempts/{event['attempt_id']}/"
    for output in outputs:
        key = output["object_key"]
        if not key.startswith(prefix) or any(p in {".", ".."} for p in key.split("/")):
            raise MediaError(422, "output is outside the accepted attempt")
    current = await session.get(ProcessingProjection, asset.id)
    if not validate_transition(current, event):
        return False
    if current is None:
        current = ProcessingProjection(asset_id=asset.id)
        session.add(current)
    current.job_id = job_id
    current.attempt_id = UUID(event["attempt_id"]) if event["attempt_id"] else None
    current.attempt_number = number
    current.state_version = event["state_version"]
    current.status = status
    current.source = source
    current.outputs = outputs
    current.error = payload.get("error")
    current.result_hash = fingerprint({k: v for k, v in event.items() if k != "message_id"})
    asset.processing_job_id = job_id
    asset.submission_state = "submitted"
    asset.submitted_at = asset.submitted_at or now()
    asset.last_submit_error = None
    await session.flush()
    return True


async def source_for_asset(session, asset):
    """A2's accepted immutable revision adapter (no public descriptors)."""
    from media.services.direct_intake import source_for_asset as accepted_source

    derived = await session.get(DerivedSource, asset.id)
    descriptor = derived.descriptor if derived else await accepted_source(session, asset.id)
    if not descriptor:
        raise MediaError(409, "accepted immutable source unavailable")
    return descriptor


async def read_job(session, asset):
    current = await session.get(ProcessingProjection, asset.id)
    if current is None:
        return None
    return ProjectedJob(
        job_id=current.job_id,
        status=current.status,
        outputs=current.outputs,
        error=current.error,
    )


async def public_job(session, asset, storage, settings):
    job = await read_job(session, asset)
    result = PublicJob(
        id=asset.id,
        filename=asset.filename,
        status="queued",
        submission_status=asset.submission_state,
        processing_job_id=asset.processing_job_id,
    )
    if asset.submission_state == "error":
        result.status = "failed"
        result.error = asset.last_submit_error
    if job:
        # Deleted assets are filtered by the caller; cancellation remains hidden.
        result.status = "failed" if job.status == "cancelled" else job.status
        result.error = job.error if job.status in {"failed", "cancelled"} else None
        if job.status == "done":
            primary = next(o for o in job.outputs if o.kind == "primary")
            result.output_url = await storage.sign_output(primary.object_key)
            hls = next((o for o in job.outputs if o.kind == "hls_manifest"), None)
            if hls:
                result.hls_url = (
                    f"{settings.api_public_prefix.rstrip('/')}/jobs/{asset.id}/hls/"
                    f"{PurePosixPath(hls.object_key).name}"
                )
    return result
