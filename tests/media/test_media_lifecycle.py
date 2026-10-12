from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from media.errors import MediaError, PeerError
from media.models import CleanupIntent, RetryIntent, StagedObject, now
from media.schemas.edit import EditRequest
from media.schemas.peer import Output
from media.services import lifecycle


@pytest.mark.parametrize("failure", [None, 503, 409, 410, "storage"])
async def test_durable_dispatch_outage_replay_and_definitive_rejection(
    session, peer, storage, asset, job, failure
):
    session.scalar.return_value = asset
    asset.submission_state = "pending"
    peer.submit.return_value = job
    if failure == "storage":
        storage.source_grant.side_effect = OSError()
    elif failure:
        peer.submit.side_effect = PeerError(failure)
    await lifecycle.dispatch(session, peer, storage, asset.id)
    assert asset.submit_attempts == 1
    if failure is None:
        assert asset.submission_state == "submitted" and asset.processing_job_id == job.job_id
        assert "operations" not in peer.submit.call_args.args[1]
        assert asset.last_submit_error is None
    else:
        assert asset.submission_state == ("error" if failure in (409, 410) else "pending")
        assert asset.last_submit_error and asset.next_submit_at > now()


async def test_dispatch_tombstone_or_already_submitted_never_calls_processing(
    session, peer, storage, asset
):
    session.scalar.return_value = asset
    await lifecycle.dispatch(session, peer, storage, asset.id)
    asset.deleted_at = now()
    asset.submission_state = "pending"
    await lifecycle.dispatch(session, peer, storage, asset.id)
    peer.submit.assert_not_awaited()


async def test_dispatch_edit_preserves_operation_order(session, peer, storage, asset, job):
    asset.submission_state = "pending"
    asset.operations = [{"operation": "clip", "params": {"start": 0, "end": 3}}]
    session.scalar.return_value = asset
    peer.submit.return_value = job
    await lifecycle.dispatch(session, peer, storage, asset.id)
    assert peer.submit.call_args.args[1]["operations"] == asset.operations


@pytest.mark.parametrize("field", ["owner_id", "asset_id", "job_id", "source"])
async def test_live_status_checks_entire_durable_link(asset, job, peer, field):
    peer.read.return_value = job
    if field == "source":
        job.source.sha256 = "b" * 64
    else:
        setattr(job, field, uuid4())
    with pytest.raises(MediaError) as error:
        await lifecycle.live_job(peer, asset)
    assert error.value.status_code == 503


async def test_live_status_missing_known_job_is_unavailable(asset, peer):
    peer.read.side_effect = PeerError(404)
    with pytest.raises(MediaError) as error:
        await lifecycle.live_job(peer, asset)
    assert error.value.status_code == 503


@pytest.mark.parametrize(
    "state", ["pending", "error", "queued", "processing", "failed", "done", "done-no-primary"]
)
async def test_public_projection_never_invents_outputs(asset, job, storage, settings, state):
    if state in ("pending", "error"):
        asset.submission_state = state
        asset.last_submit_error = "immutable submission rejected"
        job = None
    else:
        job.status = "done" if state == "done-no-primary" else state
        job.error = "controlled failure"
        if state == "done":
            job.outputs = [
                Output(
                    kind="primary",
                    object_key="job/attempt/output.mkv",
                    media_type="video/x-matroska",
                ),
                Output(
                    kind="hls_manifest",
                    object_key="job/attempt/hls/master.m3u8",
                    media_type="application/vnd.apple.mpegurl",
                ),
            ]
    if state == "done-no-primary":
        with pytest.raises(MediaError):
            await lifecycle.projection(asset, job, storage, settings)
        return
    result = await lifecycle.projection(asset, job, storage, settings)
    if state == "done":
        assert result.output_url and result.hls_url == f"/api/jobs/{asset.id}/hls/master.m3u8"
    else:
        assert result.output_url is None and result.hls_url is None
    if state in ("failed", "error"):
        assert result.status == "failed" and result.error


async def test_status_batch_missing_linked_record_never_appears_pending(
    asset, peer, storage, settings
):
    peer.batch.return_value = []
    with pytest.raises(MediaError) as error:
        await lifecycle.project_page([asset], peer, storage, settings)
    assert error.value.status_code == 503
    peer.batch.side_effect = PeerError()
    with pytest.raises(MediaError):
        await lifecycle.project_page([asset], peer, storage, settings)


async def test_status_batch_pending_has_no_peer_dependency(asset, peer, storage, settings):
    asset.submission_state = "pending"
    results = await lifecycle.project_page([asset], peer, storage, settings)
    assert results[0].submission_status == "pending"
    peer.batch.assert_not_awaited()


@pytest.mark.parametrize("kind", ["new", "pending", "keyed", "conflict", "deleted", "unsubmitted"])
async def test_retry_reservation_immutable_identity_and_state(session, asset, kind):
    session.scalar.return_value = asset
    intent = RetryIntent(id=uuid4(), asset_id=asset.id)
    key = uuid4() if kind in ("keyed", "conflict") else None
    if kind in ("keyed", "conflict"):
        digest = lifecycle.fingerprint({"asset_id": str(asset.id)})
        session.get.side_effect = [
            SimpleNamespace(request_hash="other" if kind == "conflict" else digest),
            intent,
        ]
    if kind == "pending":
        session.scalar.side_effect = [asset, intent]
    if kind == "new":
        session.scalar.side_effect = [asset, None]
    if kind == "deleted":
        asset.deleted_at = now()
    if kind == "unsubmitted":
        asset.submission_state = "pending"
    if kind in ("conflict", "deleted", "unsubmitted"):
        with pytest.raises(MediaError):
            await lifecycle.reserve_retry(session, asset.owner_id, asset.id, key)
    else:
        identity = await lifecycle.reserve_retry(session, asset.owner_id, asset.id, key)
        assert identity == (intent.id if kind != "new" else session.add.call_args.args[0].id)


@pytest.mark.parametrize(
    "outcome", ["confirmed", "rejected", "deleted", "ok", "lost", "conflict", "gone", "mismatch"]
)
async def test_retry_dispatch_commits_outcome_before_public_error(
    session, asset, peer, job, outcome
):
    intent = RetryIntent(id=uuid4(), asset_id=asset.id, attempts=0)
    session.get.return_value = intent
    session.scalar.return_value = asset
    peer.retry.return_value = job
    if outcome == "confirmed":
        intent.confirmed_at = now()
    if outcome == "rejected":
        intent.rejected_at = now()
    if outcome == "deleted":
        asset.deleted_at = now()
    if outcome in ("lost", "conflict", "gone"):
        peer.retry.side_effect = PeerError({"lost": 503, "conflict": 409, "gone": 410}[outcome])
    if outcome == "mismatch":
        job.asset_id = uuid4()
    if outcome in ("ok", "confirmed"):
        assert await lifecycle.dispatch_retry(session, peer, intent.id) == asset.id
        assert intent.confirmed_at
    else:
        with pytest.raises(MediaError):
            await lifecycle.dispatch_retry(session, peer, intent.id)
    if outcome in ("lost", "conflict", "gone", "mismatch"):
        assert intent.last_error and intent.next_try_at > now()
    if outcome in ("conflict", "gone"):
        assert intent.rejected_at


async def test_delete_tombstone_idempotence(session, asset):
    session.scalar.return_value = asset
    assert await lifecycle.tombstone(session, asset.id, asset.owner_id) is asset
    assert asset.deleted_at and isinstance(session.add.call_args.args[0], CleanupIntent)
    session.add.reset_mock()
    await lifecycle.tombstone(session, asset.id, asset.owner_id)
    session.add.assert_not_called()


@pytest.mark.parametrize(
    "mode", ["none", "live", "completed", "cancel-fails", "source-fails", "ok", "acked"]
)
async def test_cleanup_orders_cancel_ack_before_owned_source_delete(
    session, asset, peer, storage, mode
):
    asset.deleted_at = now() if mode != "live" else None
    intent = CleanupIntent(asset_id=asset.id, attempts=0)
    session.scalar.return_value = asset
    session.get.return_value = None if mode == "none" else intent
    if mode == "completed":
        intent.source_deleted_at = now()
    if mode == "cancel-fails":
        peer.cancel.side_effect = PeerError()
    if mode == "source-fails":
        storage.delete_source.side_effect = OSError()
    if mode == "acked":
        intent.processing_deleted_at = now()
    await lifecycle.cleanup(session, peer, storage, asset.id)
    if mode in ("none", "live", "completed", "cancel-fails"):
        storage.delete_source.assert_not_awaited()
    if mode == "cancel-fails":
        assert intent.processing_deleted_at is None
    if mode == "source-fails":
        assert intent.processing_deleted_at and not intent.source_deleted_at
    if mode == "acked":
        peer.cancel.assert_not_awaited()
    if mode in ("ok", "acked"):
        assert intent.processing_deleted_at and intent.source_deleted_at
        peer.cancel.assert_awaited_once_with(asset.owner_id, asset.id) if mode == "ok" else None


@pytest.mark.parametrize(
    "mode", ["replay", "pending", "processing", "no-primary", "copy-fails", "ok"]
)
async def test_edit_uses_independent_copy_and_saved_operations(
    session, asset, job, peer, storage, monkeypatch, mode
):
    request = EditRequest(operations=[{"operation": "clip", "params": {"start": 0, "end": 3}}])
    session.scalar.return_value = asset
    prior = asset if mode == "replay" else None
    monkeypatch.setattr(lifecycle, "replay", AsyncMock(return_value=prior))
    if mode == "pending":
        asset.submission_state = "pending"
    job.status = "processing" if mode == "processing" else "done"
    if mode != "no-primary":
        job.outputs = [
            Output(kind="primary", object_key="parent/output.mp4", media_type="video/mp4")
        ]
    peer.read.return_value = job
    stage = StagedObject(key="stage")
    session.get.return_value = stage
    storage.copy_output_source.return_value = (50, "b" * 64)
    if mode == "copy-fails":
        storage.copy_output_source.side_effect = OSError()

    async def accept(*args):
        return args[2]

    monkeypatch.setattr(lifecycle, "accept", accept)
    if mode in ("pending", "processing", "no-primary", "copy-fails"):
        with pytest.raises(MediaError):
            await lifecycle.edit(session, peer, storage, asset.owner_id, asset.id, request, uuid4())
    else:
        result = await lifecycle.edit(
            session, peer, storage, asset.owner_id, asset.id, request, uuid4()
        )
        if mode == "ok":
            assert stage.write_uncertain is False
            assert result.source_key != asset.source_key
            assert (
                result.source_asset_id == asset.id
                and result.operations == request.stored_operations()
            )
        else:
            assert result is asset
