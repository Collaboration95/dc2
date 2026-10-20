"""Verify login's connection lifetime using a real, one-slot SQLAlchemy pool."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import Response
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from media.api import auth
from media.errors import MediaError
from media.models import User
from media.schemas.public import Credentials, UserResponse


@pytest.mark.parametrize("identity", ["valid", "wrong-password", "unknown"])
async def test_login_releases_read_connection_before_password_verification(
    settings, monkeypatch, identity
):
    # Adapt the synchronous SQLite Session to the route's async calls. This uses
    # the real ORM transaction/pool lifecycle without an external DB or driver.
    engine = create_engine("sqlite://", poolclass=QueuePool, pool_size=1, max_overflow=0)
    User.__table__.create(engine)
    owner_id = uuid4()
    with Session(engine) as seed:
        seed.add(
            User(
                id=owner_id, email="known@example.com", password_hash="stored-hash", role="operator"
            )
        )
        seed.commit()

    queries = []
    event.listen(engine, "before_cursor_execute", lambda c, cur, sql, *args: queries.append(sql))
    verified = []
    response = Response()
    try:
        with Session(engine, expire_on_commit=False) as database:

            @asynccontextmanager
            async def transaction():
                with database.begin():
                    yield

            session = SimpleNamespace(
                begin=transaction, scalar=AsyncMock(side_effect=database.scalar)
            )

            def verify(password, password_hash):
                # The hook runs in the existing bcrypt thread-pool boundary.
                # A login waiting here must occupy no database connection.
                assert (database.in_transaction(), engine.pool.checkedout()) == (False, 0)
                verified.append((password, password_hash))
                return identity == "valid"

            monkeypatch.setattr(auth, "verify_password", verify)
            body = Credentials(
                email="unknown@example.com" if identity == "unknown" else "KNOWN@example.com",
                password="valid-password" if identity == "valid" else "wrong-password",
            )
            if identity == "valid":
                result = await auth.login(body, session, response, settings)
                public = UserResponse.model_validate(result)
                assert public.id == owner_id and public.role == "operator"
                assert "Secure" in response.headers["set-cookie"]
            else:
                with pytest.raises(MediaError) as error:
                    await auth.login(body, session, response, settings)
                assert error.value.status_code == 401
                assert "set-cookie" not in response.headers

            assert verified == [
                (body.password, auth.DUMMY_HASH if identity == "unknown" else "stored-hash")
            ]
            session.scalar.assert_awaited_once()
            assert len(queries) == 1 and queries[0].startswith("SELECT")
            assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()
