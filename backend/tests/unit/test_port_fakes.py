"""IT-1: every frozen port has a deterministic fake."""

from __future__ import annotations

from fairpool.fakes import (
    FakeAI,
    FakeAiRunLogger,
    FakeAllocationRead,
    FakeAuditLog,
    FakeBeacon,
    FakeClock,
    FakeIdempotencyStore,
    FakeJobQueue,
    FakeLedger,
    FakeMerchantAuth,
    FakeMerchantDirectory,
    FakeNotifier,
    FakeSearch,
    FakeSearchIndexer,
)
from fairpool.ports import (
    AIClient,
    AiRunLogger,
    AllocationReadService,
    AuditLog,
    BeaconClient,
    Clock,
    IdempotencyStore,
    JobQueue,
    Ledger,
    MerchantAuth,
    MerchantDirectory,
    Notifier,
    SearchIndexer,
    SearchService,
)


def test_every_port_has_a_fake():
    pairs = (
        (FakeClock(), Clock),
        (FakeJobQueue(), JobQueue),
        (FakeAuditLog(), AuditLog),
        (FakeIdempotencyStore(), IdempotencyStore),
        (FakeLedger(), Ledger),
        (FakeNotifier(), Notifier),
        (FakeBeacon(), BeaconClient),
        (FakeAiRunLogger(), AiRunLogger),
        (FakeAI(), AIClient),
        (FakeSearch(), SearchService),
        (FakeSearchIndexer(), SearchIndexer),
        (FakeMerchantAuth(), MerchantAuth),
        (FakeAllocationRead(), AllocationReadService),
        (FakeMerchantDirectory(), MerchantDirectory),
    )
    for fake, port in pairs:
        assert isinstance(fake, port), port
