from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from media.api.v1_jobs import page
from media.models import Asset, User, now
from media.projection_models import ProcessingProjection


@pytest.mark.parametrize("page_size", [1, 12, 50, 200])
async def test_asset_page_uses_one_query_and_preserves_visibility_and_order(page_size):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    statements = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def count_statement(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    owner, peer = uuid4(), uuid4()
    stamp = now()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(User.__table__.create)
            await connection.run_sync(Asset.__table__.create)
            await connection.run_sync(ProcessingProjection.__table__.create)

        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add_all(
                [
                    User(id=owner, email="owner@example.test", password_hash="x", role="user"),
                    User(id=peer, email="peer@example.test", password_hash="x", role="user"),
                ]
            )
            assets = [
                Asset(
                    id=uuid4(),
                    owner_id=owner,
                    filename=f"asset-{i}",
                    source_key=f"source/{i}",
                    source_revision=1,
                    source_size_bytes=10,
                    source_sha256="a" * 64,
                    source_media_type="video/mp4",
                    submission_state="pending",
                    processing_job_id=uuid4(),
                    operations=[],
                    submit_attempts=0,
                    next_submit_at=stamp,
                    created_at=stamp + timedelta(seconds=i),
                )
                for i in range(page_size)
            ]
            hidden = Asset(
                id=uuid4(),
                owner_id=peer,
                filename="peer",
                source_key="source/peer",
                source_revision=1,
                source_size_bytes=10,
                source_sha256="b" * 64,
                source_media_type="video/mp4",
                submission_state="pending",
                operations=[],
                submit_attempts=0,
                next_submit_at=stamp,
                created_at=stamp + timedelta(days=1),
            )
            deleted = Asset(
                id=uuid4(),
                owner_id=owner,
                filename="deleted",
                source_key="source/deleted",
                source_revision=1,
                source_size_bytes=10,
                source_sha256="c" * 64,
                source_media_type="video/mp4",
                submission_state="pending",
                operations=[],
                submit_attempts=0,
                next_submit_at=stamp,
                created_at=stamp + timedelta(days=2),
                deleted_at=stamp,
            )
            session.add_all([*assets, hidden, deleted])
            result_asset = assets[-1]
            session.add(
                ProcessingProjection(
                    asset_id=result_asset.id,
                    job_id=result_asset.processing_job_id,
                    attempt_number=0,
                    state_version=1,
                    status="processing",
                    source={},
                    outputs=[],
                    result_hash="d" * 64,
                )
            )
            await session.commit()

            statements.clear()
            rows = await page(session, owner, object(), object(), page_size, 0)
            assert len(statements) == 1
            assert len(rows) == page_size
            assert [job.id for job in rows] == [
                asset.id for asset in sorted(assets, key=lambda item: item.created_at, reverse=True)
            ]
            assert rows[0].status == "processing"  # The joined projection is visible.
            assert all(
                job.status == "accepted" for job in rows[1:]
            )  # No projection is still accepted.
            assert hidden.id not in {job.id for job in rows}
            assert deleted.id not in {job.id for job in rows}

            statements.clear()
            admin_rows = await page(session, None, object(), object(), page_size + 1, 0)
            assert len(statements) == 1
            assert len(admin_rows) == page_size + 1
            assert hidden.id in {job.id for job in admin_rows}
            assert deleted.id not in {job.id for job in admin_rows}
    finally:
        await engine.dispose()
