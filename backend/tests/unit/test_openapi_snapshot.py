"""T01B03: the committed frontend OpenAPI snapshot matches the app."""

from __future__ import annotations

import json
from pathlib import Path

from fairpool.api.app import create_app

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = ROOT / "frontend/openapi.json"


def test_frontend_snapshot_is_current():
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert committed == create_app().openapi()
