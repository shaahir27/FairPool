"""Merchant Agent API sub-application (T01B01; api.md section 4.3).

Routes are relative here; the parent mounts this app at ``/merchant-api/v1``.
The exporter prefixes the paths for the APIMatic document.
"""

from __future__ import annotations

from fastapi import FastAPI

from fairpool.api.deps import MERCHANT_KEY_LIMIT
from fairpool.infra.limits import SlidingWindowLimiter

from . import routes_fulfillment, routes_lots_bids

app = FastAPI(
    title="FairPool Merchant Agent API",
    version="0.1.0",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url=None,
)
# The 120/min-per-key window is this sub-app's own state, so the parent's routes can
# never spend a key's budget; ``require_merchant_key`` keys it by the key's prefix.
app.state.merchant_key_limiter = SlidingWindowLimiter(limit=MERCHANT_KEY_LIMIT)
app.include_router(routes_lots_bids.router)
app.include_router(routes_fulfillment.router)
