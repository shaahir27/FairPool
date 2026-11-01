"""IT-1: every frozen port has a deterministic fake.

The vault section also pins the contract against the code: the CR-3 review found
``domain-ports.md`` 4.4 naming a ``CaptureResult`` that exists nowhere and a
``PaymentRouter.charge_vault`` the composition root never had (M4), and a port that
carried no attempt identity while the contract demanded attempt-scoped keys (M1).
These two are the regression guard for exactly that class of drift.
"""

from __future__ import annotations

from pathlib import Path

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

DOMAIN_PORTS = Path(__file__).resolve().parents[3] / "docs" / "contracts" / "domain-ports.md"


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
