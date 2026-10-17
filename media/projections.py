"""Version-fenced result application and local public read projection.

``apply_result`` runs inside media.messaging.consume_result's transaction. The
inbox and projection commit together before the SQS adapter acknowledges delivery.
No function in this module opens a Processing HTTP or database connection.
"""

from pathlib import PurePosixPath
from uuid import UUID

from pydantic import BaseModel

from media.errors import MediaError
from media.models import CleanupIntent, now
from media.projection_models import ProcessingProjection
from media.repositories.assets import fingerprint, get_asset
from media.schemas.outputs import Output
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
        if payload["status"] == "cancelled":
            return True
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
    if event["job_id"] is None and event["attempt_id"] is None:
        return await confirm_cancellation(session, asset, event, no_job=True)
    if asset.deleted_at:
        if event["payload"].get("status") == "cancelled":
            return await confirm_cancellation(session, asset, event, no_job=False)
        return False  # Durable tombstone dominates every late non-cancel result.
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


async def confirm_cancellation(session, asset, event, *, no_job):
    """Only a consumed durable result authorizes later source cleanup."""
    from media.messaging_models import MediaOutbox

    payload = event["payload"]
    if not asset.deleted_at or payload.get("status") != "cancelled":
        raise MediaError(409, "cancellation acknowledgement requires a tombstone")
    current = await session.get(ProcessingProjection, asset.id)
    if no_job:
        if payload.get("cancellation_confirmed") is not True:
            raise MediaError(422, "unconfirmed cancellation acknowledgement")
        if asset.processing_job_id or current is not None:
            raise MediaError(409, "no-job cancellation conflicts with accepted job")
        try:
            command_id = UUID(payload["command_message_id"])
        except (KeyError, ValueError, TypeError) as exc:
            raise MediaError(422, "invalid cancellation command identity") from exc
        command = await session.get(MediaOutbox, command_id)
        if (
            command is None
            or command.queue != "processing-commands"
            or any(
                command.body.get(k) != value
                for k, value in {
                    "kind": "cancel",
                    "owner_id": str(asset.owner_id),
                    "asset_id": str(asset.id),
                    "job_id": None,
                }.items()
            )
        ):
            raise MediaError(409, "cancellation acknowledgement does not match command")
        if event["source"] is not None or payload.get("outputs"):
            raise MediaError(422, "no-job cancellation cannot publish source or outputs")
    else:
        if not event["source"] or not event["attempt_id"]:
            raise MediaError(422, "cancelled job requires immutable source and attempt")
        if asset.processing_job_id and str(asset.processing_job_id) != event["job_id"]:
            raise MediaError(409, "cancellation belongs to another Processing job")
        if event["source"] != await source_for_asset(session, asset):
            raise MediaError(409, "cancellation source differs from accepted source")
        number = payload.get("attempt_number")
        if type(number) is not int or number < 1 or payload.get("outputs"):
            raise MediaError(422, "invalid cancelled attempt")
        if not validate_transition(current, event):
            # An identical replay remains acknowledged through the existing ledger;
            # a stale version can never grant new cleanup authority.
            return False
    intent = await session.get(CleanupIntent, asset.id, with_for_update=True)
    if intent is None:
        raise MediaError(409, "cancellation cleanup intent is absent")
    intent.processing_deleted_at = intent.processing_deleted_at or now()
    intent.next_try_at = now()
    if current is not None:
        current.state_version = event["state_version"]
        current.attempt_id = UUID(event["attempt_id"])
        current.attempt_number = payload["attempt_number"]
        current.status = "cancelled"
        current.outputs = []
        current.result_hash = fingerprint({k: v for k, v in event.items() if k != "message_id"})
    await session.flush()
    return True


async def source_for_asset(session, asset):
    """A2's accepted immutable revision adapter (no public descriptors)."""
    from media.services.direct_intake import source_for_asset as accepted_source

    descriptor = await accepted_source(session, asset)
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
        # Before any Processing result is projected the upload is only accepted;
        # "queued" would claim Processing has acknowledged the work.
        status="accepted" if asset.submission_state == "pending" else "queued",
        submission_status=asset.submission_state,
        processing_job_id=asset.processing_job_id,
    )
    if asset.submission_state == "error":
        result.status = "failed"
        result.error = asset.last_submit_error
    if job:
        # Deleted assets are filtered by the caller; a cancelled projection is its
        # own terminal state, never a failure the user could retry.
        result.status = job.status
        if job.status == "cancelled":
            result.error = "Processing was cancelled"
        else:
            result.error = job.error if job.status == "failed" else None
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
