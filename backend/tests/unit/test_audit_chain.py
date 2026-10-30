"""T01A02: the audit chain reproduces the published vector exactly."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fairpool.fakes.audit import FakeAuditLog

ROOT = Path(__file__).resolve().parents[3]
VECTOR = ROOT / "docs/contracts/vectors/fairness_v1.json"


async def test_fake_chain_matches_the_vector_hashes():
    entries = json.loads(VECTOR.read_text(encoding="utf-8"))["audit_chain"]
    timestamps = iter(
        datetime.fromisoformat(entry["row"]["created_at"].replace("Z", "+00:00"))
        for entry in entries
    )
    audit = FakeAuditLog(clock=lambda: next(timestamps))
    for entry in entries:
        row = entry["row"]
        await audit.append(
            None,  # type: ignore[arg-type]
            actor=row["actor"],
            action=row["action"],
            subject_type=row["subject_type"],
            subject_id=row["subject_id"],
            payload=row["payload"],
        )
    assert [entry["hash"] for entry in audit.rows] == [entry["hash"] for entry in entries]
    assert audit.verify_chain()
