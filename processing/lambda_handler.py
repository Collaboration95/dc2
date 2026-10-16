"""Separately packaged API Gateway HTTP API payload-v2 Processing entrypoint."""

from contracts.gateway import GatewayAdapter
from processing.v1_api import app

handler = GatewayAdapter(app, service="processing")
