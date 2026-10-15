import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from media.api import auth, uploads
from media.errors import MediaError


@asynccontextmanager
async def lifespan(app):
    try:
        yield
    finally:
        engine = getattr(app.state, "engine", None)
        if engine is not None:
            await engine.dispose()
            app.state.engine = None
        client = getattr(app.state, "http_client", None)
        if client is not None:
            await client.aclose()
            app.state.http_client = None


def create_app(*, v1: bool = False):
    app = FastAPI(title="FlickPond Media Management", version="1.0.0", lifespan=lifespan)

    @app.exception_handler(MediaError)
    async def media_error(request: Request, exc: MediaError):
        return JSONResponse({"error": exc.message}, status_code=exc.status_code)

    async def unavailable(request: Request, exc: Exception):
        return JSONResponse({"error": "Media dependency unavailable"}, status_code=503)

    for exception in (SQLAlchemyError, OSError, TimeoutError):
        app.add_exception_handler(exception, unavailable)

    @app.get("/health")
    async def health(request: Request):
        if getattr(request.state, "gateway_v1", False):
            return {
                "status": "ok",
                "service": "media",
                "version": os.environ.get("MEDIA_RELEASE_VERSION", "v1"),
            }
        return {"status": "ok"}

    if v1:
        from media.api import v1_hls, v1_jobs

        # Reuse the direct-intake endpoints and their authored response metadata.
        # The deprecated multipart route carries a Peer dependency and stays out.
        reservations = APIRouter()
        reservations.routes.extend(
            route
            for route in uploads.router.routes
            if route.endpoint in (uploads.reserve_upload, uploads.finalize_upload)
        )
        routers = (auth.router, reservations, v1_jobs.router, v1_jobs.admin_router, v1_hls.router)
    else:
        from media.api import hls, jobs, source_access

        routers = (
            auth.router,
            uploads.router,
            jobs.router,
            jobs.admin_router,
            hls.router,
            source_access.router,
        )
    for router in routers:
        app.include_router(router)
    return app


def create_v1_app():
    return create_app(v1=True)


app = create_app()
