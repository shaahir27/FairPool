"""Merchant Agent API sub-application (T01B01; api.md section 4.3).

Routes are relative here; the parent mounts this app at ``/merchant-api/v1``.
The exporter prefixes the paths for the APIMatic document.
"""

from __future__ import annotations

from fastapi import FastAPI

from . import routes_fulfillment, routes_lots_bids

app = FastAPI(
    title="FairPool Merchant Agent API",
    version="0.1.0",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url=None,
)
app.include_router(routes_lots_bids.router)
app.include_router(routes_fulfillment.router)
