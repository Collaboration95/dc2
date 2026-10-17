"""After finalize, nothing may read the staging key without its pinned VersionId.

The staging key stays writable by a replayed upload grant until that grant expires, and a
versioned bucket answers an unversioned GET with the newest object. These tests pin the
SQL-side half of the defence; the object-store half is in tests/v1/test_direct_intake_s3.py.
"""

import ast
import hashlib
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alembic.script import ScriptDirectory

from media.errors import MediaError
from media.models import now
from media.services import direct_intake as intake
from media.upload_models import SourceVersion, UploadReservation

ROOT = Path(__file__).resolve().parents[2]
# Captured at import: the suite-wide autouse fixture replaces the module attribute.
REAL_PINNED_VERSION = intake.pinned_version


@pytest.fixture
def reservation(user, video):
    return UploadReservation(
        id=uuid4(),
        owner_id=user.id,
        request_id=uuid4(),
        request_hash="a" * 64,
        asset_id=uuid4(),
        filename="clip.mp4",
        bucket="source",
        key=f"staging/{user.id}/{uuid4()}/source",
        content_type="video/mp4",
        size_bytes=len(video),
        sha256=hashlib.sha256(video).hexdigest(),
        expires_at=now() + timedelta(minutes=15),
        finalized_at=None,
    )


async def test_reused_grant_after_finalize_cannot_change_the_accepted_source(
    session, storage, reservation
):
    session.scalar.return_value = reservation
    storage.verify_direct_upload.return_value = "accepted-version"
    enqueue = AsyncMock()
    request = intake.FinalizeRequest(request_id=reservation.request_id)
    asset = await intake.finalize(
        session, storage, reservation.owner_id, reservation.id, request, enqueue=enqueue
    )
    accepted = intake.source(reservation)
    assert accepted["version_id"] == "accepted-version"

    # The attacker replays the still-valid grant: the object store now has a newer version,
    # and any re-verification would pin it. Finalize must not look at storage again.
    storage.verify_direct_upload.return_value = "attacker-version"
    session.get.return_value = asset
    again = await intake.finalize(
        session, storage, reservation.owner_id, reservation.id, request, enqueue=enqueue
    )

    assert again is asset
    storage.verify_direct_upload.assert_awaited_once()
    enqueue.assert_awaited_once()
    assert reservation.version_id == "accepted-version"
    assert await intake.source_for_asset(session, asset) == accepted


async def test_a_source_whose_key_differs_from_the_asset_is_refused(session, reservation, asset):
    reservation.version_id = "v1"
    reservation.finalized_at = now()
    session.scalar.return_value = reservation
    asset.id = reservation.asset_id
    asset.source_key = reservation.key
    assert (await intake.source_for_asset(session, asset))["version_id"] == "v1"
    asset.source_key = "staging/other-owner/other/source"
    with pytest.raises(MediaError) as refusal:
        await intake.source_for_asset(session, asset)
    assert refusal.value.status_code == 409


async def test_legacy_signed_url_readers_receive_the_pinned_version(
    session, reservation, asset
):
    reservation.version_id = "pinned"
    reservation.finalized_at = now()
    asset.id, asset.source_key = reservation.asset_id, reservation.key
    session.scalar.return_value = reservation
    assert await REAL_PINNED_VERSION(session, asset) == "pinned"

    session.scalar.return_value = None
    session.get.return_value = SourceVersion(
        asset_id=asset.id,
        bucket="source",
        key=asset.source_key,
        version_id="derived-pin",
        sha256="b" * 64,
        size_bytes=1,
        content_type="video/mp4",
    )
    assert await REAL_PINNED_VERSION(session, asset) == "derived-pin"

    session.get.return_value = None
    assert await REAL_PINNED_VERSION(session, asset) is None


def test_no_media_code_signs_a_source_url_without_choosing_a_version():
    """Static audit: a new unversioned source reader fails here, not in production."""
    offenders = []
    for path in (ROOT / "media").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "source_grant"
                and len(node.args) + len(node.keywords) < 2
            ):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


def test_finalized_reservation_pin_constraint_matches_the_migration():
    constraint = next(
        c
        for c in UploadReservation.__table__.constraints
        if getattr(c, "name", None) == "ck_upload_reservations_finalized_has_pin"
    )
    scripts = ScriptDirectory(str(ROOT / "media/migrations"))
    assert scripts.get_heads() == ["media_0008"]  # the pin check came in at 0007
    module = scripts.get_revision("media_0007").module
    assert str(constraint.sqltext) == module.PREDICATE
