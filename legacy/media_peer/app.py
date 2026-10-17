"""The retired peer-calling Media app (``legacy.media_peer.app:app``), local stack only."""

from contextlib import asynccontextmanager

from legacy.media_peer import hls, jobs, source_access
from legacy.media_peer import uploads as multipart
from media.api import auth
from media.api import uploads as direct
from media.main import build_app, lifespan


@asynccontextmanager
async def peer_lifespan(app):
    try:
        async with lifespan(app):
            yield
    finally:
        client = getattr(app.state, "http_client", None)
        if client is not None:
            await client.aclose()
            app.state.http_client = None


def create_app():
    return build_app(
        (
            auth.router,
            multipart.router,
            direct.router,
            jobs.router,
            jobs.admin_router,
            hls.router,
            source_access.router,
        ),
        lifespan=peer_lifespan,
    )


app = create_app()
