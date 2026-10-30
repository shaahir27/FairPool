"""T01A02: fake idempotency behaviour matches the contract."""

from __future__ import annotations

import pytest

from fairpool.fakes.idempotency import FakeIdempotencyStore
from fairpool.ports import IdemConflict, IdemNew, IdemReplay


async def test_new_complete_replay_and_conflicts():
    store = FakeIdempotencyStore()
    key = "entry:pool-1:user-1"
    scope = "entry.create"
    request_hash = "a" * 64

    assert isinstance(
        await store.begin(None, key=key, scope=scope, request_hash=request_hash), IdemNew
    )  # type: ignore[arg-type]
    assert isinstance(
        await store.begin(None, key=key, scope=scope, request_hash=request_hash), IdemConflict
    )  # type: ignore[arg-type]

    await store.complete(None, key=key, response={"entry_id": "e1"})  # type: ignore[arg-type]
    replay = await store.begin(None, key=key, scope=scope, request_hash=request_hash)  # type: ignore[arg-type]
    assert isinstance(replay, IdemReplay)
    assert replay.response == {"entry_id": "e1"}

    assert isinstance(
        await store.begin(None, key=key, scope=scope, request_hash="b" * 64),  # type: ignore[arg-type]
        IdemConflict,
    )
    assert isinstance(
        await store.begin(None, key=key, scope="other.scope", request_hash=request_hash),  # type: ignore[arg-type]
        IdemConflict,
    )


async def test_complete_requires_a_started_key():
    store = FakeIdempotencyStore()
    with pytest.raises(KeyError):
        await store.complete(None, key="missing", response={})  # type: ignore[arg-type]
