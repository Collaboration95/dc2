from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from media.errors import MediaError
from media.models import RequestKey, StagedObject
from media.repositories.assets import fingerprint, get_asset, list_assets, replay
from media.services import intake


def test_fingerprint_retains_operation_order_and_normalizes_object_order():
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})
    assert fingerprint({"ops": [1, 2]}) != fingerprint({"ops": [2, 1]})
    assert intake.safe_filename("../../bad name.mp4") == "bad_name.mp4"
    assert intake.safe_filename(None) == "upload.bin"
    assert len(intake.safe_filename("a" * 200)) == 100


@pytest.mark.parametrize("failure,code", [("type", 415), ("bytes", 415), ("size", 413)])
def test_actual_file_size_and_container_type(upload_file, monkeypatch, failure, code):
    if failure == "type":
        upload_file.headers = {"content-type": "application/pdf"}
    if failure == "bytes":
        upload_file.file = BytesIO(b"not a video")
    if failure == "size":
        monkeypatch.setattr(intake, "MAX_FILE_SIZE", 1)
    with pytest.raises(MediaError) as error:
        intake.inspect_upload(upload_file)
    assert error.value.status_code == code


def test_exact_file_limit_allows_multipart_overhead(upload_file, video, monkeypatch):
    monkeypatch.setattr(intake, "MAX_FILE_SIZE", len(video))
    assert intake.inspect_upload(upload_file)[0] == len(video)


async def test_repository_owner_filter_order_and_not_found(session, asset):
    session.scalar.return_value = asset
    assert await get_asset(session, asset.id, asset.owner_id, lock=True) is asset
    query = str(session.scalar.call_args.args[0])
    assert "owner_id" in query and "FOR UPDATE" in query and "deleted_at IS NULL" in query
    assert await get_asset(session, asset.id, None, include_deleted=True) is asset
    session.scalar.return_value = None
    with pytest.raises(MediaError):
        await get_asset(session, uuid4(), asset.owner_id)
    session.scalars.return_value = [asset]
    assert await list_assets(session, asset.owner_id, 50, 0) == [asset]
    assert "ORDER BY assets.created_at DESC, assets.id" in str(session.scalars.call_args.args[0])
    await list_assets(session, None, 50, 0)


async def test_replay_never_resurrects_tombstones_or_changes_sources(session, asset):
    assert await replay(session, asset.owner_id, "upload", None, "digest") is None
    session.get.return_value = None
    key = uuid4()
    assert await replay(session, asset.owner_id, "upload", key, "digest") is None
    session.get.return_value = RequestKey(
        owner_id=asset.owner_id,
        operation="upload",
        request_key=key,
        request_hash="digest",
        asset_id=asset.id,
    )
    session.scalar.return_value = asset
    assert await replay(session, asset.owner_id, "upload", key, "digest") is asset
    with pytest.raises(MediaError) as error:
        await replay(session, asset.owner_id, "upload", key, "changed")
    assert error.value.status_code == 409
    asset.deleted_at = asset.created_at
    with pytest.raises(MediaError) as error:
        await replay(session, asset.owner_id, "upload", key, "digest")
    assert error.value.status_code == 410


async def test_stage_discard_failure_retains_crash_cleanup_intent(session, storage):
    await intake.stage(session, "own-stage")
    assert isinstance(session.add.call_args.args[0], StagedObject)
    storage.delete_source.side_effect = OSError()
    await intake.discard_stage(session, storage, "own-stage")
    session.execute.assert_not_awaited()
    storage.delete_source.side_effect = None
    await intake.discard_stage(session, storage, "own-stage")
    assert "staged_objects.key" in str(session.execute.call_args.args[0])


async def test_accept_race_discards_only_loser_and_returns_winner(
    session, storage, asset, monkeypatch
):
    session.flush.side_effect = IntegrityError(
        "insert", {}, Exception("controlled unique collision")
    )
    winner = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(intake, "replay", AsyncMock(return_value=winner))
    assert await intake.accept(session, storage, asset, "upload", uuid4(), "digest") is winner
    storage.delete_source.assert_awaited_once_with(asset.source_key)
    assert winner.id != asset.id


async def test_accept_unrelated_constraint_or_commit_failure_has_no_false_success(
    session, storage, asset, monkeypatch
):
    monkeypatch.setattr(intake, "replay", AsyncMock(return_value=None))
    session.flush.side_effect = IntegrityError("insert", {}, Exception("controlled rejection"))
    with pytest.raises(MediaError):
        await intake.accept(session, storage, asset, "upload", uuid4(), "digest")
    session.flush.side_effect = OSError()
    with pytest.raises(OSError):
        await intake.accept(session, storage, asset, "upload", None, "digest")
    assert storage.delete_source.await_count == 2


async def test_upload_replay_has_no_object_write(session, storage, asset, upload_file, monkeypatch):
    monkeypatch.setattr(intake, "replay", AsyncMock(return_value=asset))
    assert await intake.upload(session, storage, asset.owner_id, upload_file, uuid4()) is asset
    storage.put_source.assert_not_awaited()


async def test_upload_stages_then_reserves_asset_before_any_dispatch(
    session, storage, user, upload_file, monkeypatch
):
    monkeypatch.setattr(intake, "replay", AsyncMock(return_value=None))
    staged = StagedObject(key="pending")
    session.get.return_value = staged
    asset = await intake.upload(session, storage, user.id, upload_file, uuid4())
    assert asset.operations == [] and asset.source_size_bytes > 0
    assert asset.source_key.startswith(f"sources/{user.id}/{asset.id}/")
    storage.put_source.assert_awaited_once()
    assert staged.created_at is not None
    assert any(isinstance(call.args[0], RequestKey) for call in session.add.call_args_list)


async def test_upload_storage_loss_discards_own_staged_object(
    session, storage, user, upload_file, monkeypatch
):
    monkeypatch.setattr(intake, "replay", AsyncMock(return_value=None))
    storage.put_source.side_effect = OSError()
    with pytest.raises(MediaError) as error:
        await intake.upload(session, storage, user.id, upload_file, None)
    assert error.value.status_code == 503
    assert storage.delete_source.call_args.args[0] == storage.put_source.call_args.args[0]
