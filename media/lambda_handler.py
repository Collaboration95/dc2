"""Media HTTP API payload-v2 entrypoint, sharing the canonical Gateway adapter."""

from contracts.gateway import GatewayAdapter
from media.authorizer import handler as authorizer  # noqa: F401
from media.main import create_v1_app

handler = GatewayAdapter(create_v1_app(), service="media")
