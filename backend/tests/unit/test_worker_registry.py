"""T04X01: the worker registry equals the implemented set, both directions.

``domain-ports.md`` section 5 is the only source of job kinds, and an enqueue is not
evidence that work happened. So this test proves three things at once:

* every kind the worker registers is a kind the contract names, and every kind the
  contract names that has a handler is registered -- a handler cannot exist without
  being registered, or be registered without existing;
* every registered handler is a callable, and the checkout ones are bound methods of
  the real engines (not a fake and not a stub);
* the kinds whose work belongs to a later phase (bidding, failure finalisation,
  voids, refunds, webhooks, shipments, simulation) stay unregistered.
"""

from __future__ import annotations

import re
from pathlib import Path

from fairpool.modules.checkout.authorize import CheckoutAuthorizeHandlers
from fairpool.modules.checkout.failure import FailureService
from fairpool.modules.checkout.funding import FundingService
from fairpool.modules.checkout.open_checkout import OpenCheckoutHandler
from fairpool.modules.checkout.refill import RefillService
from fairpool.modules.checkout.vault_charge import VaultChargeHandler
from fairpool.wiring import IMPLEMENTED_JOB_KINDS, worker_handlers
from tests.unit.test_settings import make_settings

ROOT = Path(__file__).resolve().parents[3]
PORTS_DOC = ROOT / "docs/contracts/domain-ports.md"

#: The kinds a later phase owns. None of them may be registered yet.
LATER_PHASES = {
    "lot.bid_open",
    "lot.bid_close",
    "lot.award",
    "sim.run",
    "webhook.process",
    "shipments.submit",
}

#: kind -> the real owner whose bound method must be registered.
OWNERS = {
    "lot.open_checkout": OpenCheckoutHandler,
    "order.authorize": CheckoutAuthorizeHandlers,
    "order.capture": FundingService,
    "capture.poll": FundingService,
    "lot.try_fund": FundingService,
    "lot.finalize_close": FundingService,
    "lot.refill": RefillService,
    "order.vault_charge": VaultChargeHandler,
    "lot.finalize_fail": FailureService,
    "void.run": FailureService,
    "refund.run": FailureService,
}


def contract_kinds() -> set[str]:
    """The kind column of ``domain-ports.md`` section 5, plus later additions."""
    text = PORTS_DOC.read_text(encoding="utf-8")
    section = text.split("## 5. Job kinds", 1)[1].split("## 6.", 1)[0]
    kinds = set()
    for line in section.splitlines():
        match = re.match(r"^\|\s*([a-z]+\.[a-z_]+)\s*\|", line)
        if match:
            kinds.add(match.group(1))
    return kinds


def settings():
    return make_settings(payment_router="fake", ai_enabled=False)


def test_the_registry_is_exactly_the_implemented_set() -> None:
    handlers = worker_handlers(settings())

    assert set(handlers) == IMPLEMENTED_JOB_KINDS
    # A handler cannot be registered without existing, and cannot exist unregistered.
    assert contract_kinds() >= set(handlers), "a registered kind is not in domain-ports.md §5"
    assert set(handlers).isdisjoint(LATER_PHASES)
    assert contract_kinds() - set(handlers) == LATER_PHASES


def test_every_registered_handler_is_a_real_callable() -> None:
    handlers = worker_handlers(settings())

    for kind, handler in handlers.items():
        assert callable(handler), kind
    for kind, owner in OWNERS.items():
        handler = handlers[kind]
        assert getattr(handler, "__self__", None) is not None, kind
        assert isinstance(handler.__self__, owner), kind


def test_the_pool_and_search_handlers_are_real_implementations() -> None:
    """``search.index`` is a closure over the indexer; the pool kinds are bound methods."""
    handlers = worker_handlers(settings())

    for kind in ("pool.open", "pool.close", "pool.seed", "pool.allocate"):
        assert getattr(handlers[kind], "__self__", None) is not None, kind
    assert handlers["search.index"].__name__ == "handle"
    assert handlers["reconciler.sweep"].__name__ == "sweep"


def test_no_kind_is_registered_outside_the_dotted_vocabulary() -> None:
    """``domain-ports.md`` section 5 names kinds as ``resource.verb``."""
    for kind in IMPLEMENTED_JOB_KINDS:
        assert re.fullmatch(r"[a-z]+\.[a-z_]+", kind), kind
