"""Emulated AWS releases backed by actual owning migrations/SQL and HTTPS smoke.

Lambda/ECS/artifact receipts are explicit test fixtures, not deployed images or
cloud timing evidence. SQL history and actual public application smoke are real.
"""

import asyncio
import copy
import os
import ssl

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.timeout(180)]


@pytest.mark.parametrize("owner", ["media", "processing"])
def test_independent_owner_release_and_failed_restore_with_real_sql(tmp_path, owner):
    if not os.environ.get("V1_RUNTIME_CONFIG"):
        pytest.skip("Explicit Lead C runtime attachment required")
    from publisher.client import PublicClient
    from scripts.aws.transport import OperationError
    from scripts.aws.v1.release import promote, restore
    from scripts.dev.v1_acceptance import app_runtime, migrate
    from tests.aws.v1.test_v1_release import setup

    with app_runtime(os.environ["V1_RUN_ID"]) as runtime:
        client = PublicClient(
            runtime["url"] + "/api/media", tmp_path / "cookies", ca_file=runtime["ca"]
        )
        from uuid import uuid4

        identity = client.authenticate(
            "register", f"release-{uuid4().hex}@example.test", "local-release-password"
        )

        def revision(which, **kwargs):
            async def read():
                import asyncpg

                data = runtime["data"]
                connection = await asyncpg.connect(
                    host="127.0.0.1",
                    port=data["postgres_port"],
                    user=which + "_runtime",
                    password="local_v1_" + which,
                    database=which + "_db",
                    ssl=ssl.create_default_context(cafile=runtime["ca"]),
                )
                try:
                    return await connection.fetchval("SELECT version_num FROM alembic_version")
                finally:
                    await connection.close()

            return asyncio.run(read())

        def smoke(*args, **kwargs):
            return (
                client.identity() == identity["id"]
                and client.request("GET", "health")["service"] == "media"
            )

        try:
            private = tmp_path / "station"
            private.mkdir(mode=0o700)
            config, aws, journal, args = setup.__wrapped__(private)
            peer = "processing" if owner == "media" else "media"
            peer_schema = revision(peer)
            peer_aliases = {
                name: copy.deepcopy(aws.aliases[name])
                for name in config["owner_functions"][peer].values()
            }
            calls = []
            original = aws.call

            def call(service, operation, payload, **kwargs):
                if service == "ecs" and operation == "run-task":
                    migrate(owner, runtime["env"])
                    calls.append(owner)
                return original(service, operation, payload, **kwargs)

            aws.call = call
            options = args(owner)
            options.update(
                target_revision=revision(owner), schema_revision=revision, public_smoke=smoke
            )
            assert promote(config, aws, journal, **options)["status"] == "promoted"
            assert calls == [owner] and revision(peer) == peer_schema
            assert {name: aws.aliases[name] for name in peer_aliases} == peer_aliases
            # A fresh journal tests failure and restoration from known-good aliases.
            second = tmp_path / "failed-station"
            second.mkdir(mode=0o700)
            config2, failed, journal2, args2 = setup.__wrapped__(second)
            original_failed = failed.call

            def failed_call(service, operation, payload, **kwargs):
                if service == "ecs" and operation == "run-task":
                    migrate(owner, runtime["env"])
                return original_failed(service, operation, payload, **kwargs)

            failed.call = failed_call
            bad = args2(owner)
            bad.update(
                target_revision=revision(owner),
                schema_revision=revision,
                public_smoke=lambda *a, **kw: False,
            )
            with pytest.raises(OperationError, match="private intent retained"):
                promote(config2, failed, journal2, **bad)
            receipt = restore(
                config2,
                failed,
                journal2,
                schema_revision=revision,
                quiescent=lambda *a, **kw: True,
                public_smoke=smoke,
                deadline=bad["deadline"],
            )
            assert receipt["status"] == "restored" and receipt["schema_rollback"] is False
            assert revision(peer) == peer_schema
            assert all(value["FunctionVersion"] == "1" for value in failed.aliases.values())
        finally:
            client.close()
