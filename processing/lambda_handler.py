"""Separately packaged API Gateway HTTP API payload-v2 Processing entrypoint."""

from contracts.gateway import GatewayAdapter
from processing.config import get_settings
from processing.database import database_ready
from processing.v1_api import app


async def readiness():
    return await database_ready(get_settings())


handler = GatewayAdapter(app, service="processing", readiness=readiness)
