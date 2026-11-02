"""Provision fixture accounts independently of public PayPal enrollment."""

from starlette.requests import Request

from fairpool.api.deps import database_session, identity_service


async def provision_buyer(client, *, email, password, display_name):
    # These HTTP fixtures use ASGITransport with an explicit database override.
    # Setup uses the existing service; the public signup gate is never disabled.
    app = client._transport.app
    service = identity_service(Request({"type": "http", "app": app}))
    async for db in app.dependency_overrides[database_session]():
        await service.register(db, email=email, password=password, display_name=display_name)
