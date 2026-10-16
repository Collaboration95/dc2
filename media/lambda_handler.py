"""Media HTTP API payload-v2 entrypoint, sharing the canonical Gateway adapter."""

from contracts.gateway import GatewayAdapter
from media.authorizer import handler as authorizer  # noqa: F401
from media.config import get_settings
from media.database import database_ready
from media.main import create_v1_app


async def readiness():
    return await database_ready(get_settings())


handler = GatewayAdapter(create_v1_app(), service="media", readiness=readiness)
