from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from media.api import auth, hls, jobs, source_access, uploads
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


def create_app():
    app = FastAPI(title="FlickPond Media Management", version="1.0.0", lifespan=lifespan)

    @app.exception_handler(MediaError)
    async def media_error(request: Request, exc: MediaError):
        return JSONResponse({"error": exc.message}, status_code=exc.status_code)

    async def unavailable(request: Request, exc: Exception):
        return JSONResponse({"error": "Media dependency unavailable"}, status_code=503)

    for exception in (SQLAlchemyError, OSError, TimeoutError):
        app.add_exception_handler(exception, unavailable)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    for router in (
        auth.router,
        uploads.router,
        jobs.router,
        jobs.admin_router,
        hls.router,
        source_access.router,
    ):
        app.include_router(router)
    return app


app = create_app()
