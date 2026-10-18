import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from media.api import auth, uploads, v1_hls, v1_jobs
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


def build_app(routers, *, lifespan=lifespan):
    """Shared shell: error mapping and /health. The router set decides which API this is."""
    app = FastAPI(title="FlickPond Media Management", version="1.0.1", lifespan=lifespan)

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

    for router in routers:
        app.include_router(router)
    return app


def create_v1_app():
    """Projections and durable commands only: Media never calls Processing."""
    return build_app(
        (auth.router, uploads.router, v1_jobs.router, v1_jobs.admin_router, v1_hls.router)
    )


app = create_v1_app()
