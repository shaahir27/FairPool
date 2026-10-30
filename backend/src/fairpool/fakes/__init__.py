"""Deterministic port fakes (T01B02 and later)."""

from __future__ import annotations

from .ai import FakeAI, FakeAICall, FakeAIInvalidJSON, FakeAITimeout
from .ai_logger import AiRunRecord, FakeAiRunLogger
from .allocation_read import AllocationCall, FakeAllocationRead
from .audit import FakeAuditLog
from .beacon import FakeBeacon
from .clock import FakeClock
from .fixtures import (
    ITEM_CENTS,
    MOQ,
    SHIPPING_CENTS_BY_ZONE,
    TAX_RATE_BPS,
    AwardFixture,
    FixtureEntry,
    make_award_fixture,
)
from .idempotency import FakeIdempotencyStore
from .jobs import FakeJob, FakeJobQueue
from .ledger import FakeLedger, LedgerRow
from .merchant_auth import FakeMerchantAuth, MerchantAuthError
from .merchant_directory import DEFAULT_PAYEE, FakeMerchantDirectory
from .notifier import FakeNotifier
from .search import FakeSearch, SearchDocument
from .search_indexer import FakeSearchIndexer

__all__ = [
    "ITEM_CENTS",
    "MOQ",
    "SHIPPING_CENTS_BY_ZONE",
    "TAX_RATE_BPS",
    "AiRunRecord",
    "AllocationCall",
    "AwardFixture",
    "DEFAULT_PAYEE",
    "FakeAI",
    "FakeAICall",
    "FakeAIInvalidJSON",
    "FakeAITimeout",
    "FakeAiRunLogger",
    "FakeAllocationRead",
    "FakeAuditLog",
    "FakeBeacon",
    "FakeClock",
    "FakeIdempotencyStore",
    "FakeJob",
    "FakeJobQueue",
    "FakeLedger",
    "FakeMerchantAuth",
    "FakeMerchantDirectory",
    "FakeNotifier",
    "FakeSearch",
    "FakeSearchIndexer",
    "FixtureEntry",
    "LedgerRow",
    "MerchantAuthError",
    "SearchDocument",
    "make_award_fixture",
]
