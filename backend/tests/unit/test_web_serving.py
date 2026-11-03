"""The hosted deployment serves the built SPA from the API origin (one origin, so the
session cookie stays first-party)."""

from __future__ import annotations

import httpx
import pytest

from fairpool.api import app as app_module
from fairpool.api.app import create_app

SPA = "<html><body>spa</body></html>"


@pytest.fixture
def web_dir(tmp_path, monkeypatch):
    root = tmp_path / "web"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(SPA, encoding="utf-8")
    (root / "assets" / "app.js").write_text("//asset", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setattr(app_module, "WEB_DIR", root)
    return root


async def _get(client, path):
    return await client.get(path)


async def test_the_api_serves_the_spa_and_its_assets(web_dir):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(None)), base_url="https://api.test"
    ) as client:
        assert (await _get(client, "/")).text == SPA
        assert (await _get(client, "/register")).text == SPA
        assert (await _get(client, "/settings/addresses")).text == SPA
        assert (await _get(client, "/assets/app.js")).text == "//asset"


async def test_api_routes_and_their_json_404_survive_the_spa_fallback(web_dir):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(None)), base_url="https://api.test"
    ) as client:
        health = await _get(client, "/health")
        assert health.status_code == 200
        missing = await _get(client, "/api/v1/nope")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "NOT_FOUND"


async def test_the_spa_fallback_cannot_read_outside_the_web_directory(web_dir):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(None)), base_url="https://api.test"
    ) as client:
        traversal = await client.get("/%2e%2e/outside.txt")
        assert traversal.text == SPA


async def test_no_web_directory_means_no_static_routes(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "WEB_DIR", tmp_path / "absent")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(None)), base_url="https://api.test"
    ) as client:
        assert (await _get(client, "/")).status_code == 404


async def test_only_fingerprinted_assets_are_cached_across_reloads(web_dir):
    (web_dir / "assets" / "app-12345678.js").write_text("//versioned", encoding="utf-8")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(None)), base_url="https://api.test"
    ) as client:
        asset = await client.get("/assets/app-12345678.js")
        assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert (await client.get("/")).headers["cache-control"] == "no-cache"
        assert "cache-control" not in (await client.get("/assets/app.js")).headers
        assert "cache-control" not in (await client.get("/health")).headers
        assert "cache-control" not in (await client.get("/assets/missing-12345678.js")).headers
