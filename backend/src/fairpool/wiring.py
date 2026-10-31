"""Composition root: select simulation before constructing network dependencies."""

from dataclasses import dataclass

from fairpool.adapters.paypal.gateway import RestPayPalGateway
from fairpool.config import Settings
from fairpool.domain.payments import NotEnabled, Payee
from fairpool.fakes.payments import FakePayPalGateway
from fairpool.ports import AwardView, PayeeRef


@dataclass
class PaymentRouter:
    name: str
    gateway: RestPayPalGateway | FakePayPalGateway
    seller: Payee

    def payee_for(self, award: AwardView, payee_ref: PayeeRef) -> Payee:
        return self.seller

    def label(self) -> str:
        return (
            "SIMULATED"
            if self.name == "fake"
            else "Sandbox demo: one test seller stands in for the winning merchant."
        )


def payment_router(
    settings: Settings, *, simulated: bool = False, fake_outcome: str = "completed"
) -> PaymentRouter:
    if simulated or settings.payment_router == "fake":
        return PaymentRouter(
            "fake", FakePayPalGateway(outcome=fake_outcome), Payee("fake@example.test", None)
        )
    if settings.payment_router != "single_seller":
        raise NotEnabled()
    return PaymentRouter(
        "single_seller",
        RestPayPalGateway(settings),
        Payee(settings.single_seller_email, settings.single_seller_merchant_id or None),
    )


def pool_service(settings: Settings):
    from fairpool.adapters.beacon.announcement import BeaconAnnouncement
    from fairpool.infra.audit import PostgresAuditLog
    from fairpool.infra.clock import DbClock
    from fairpool.infra.jobs import PostgresJobQueue
    from fairpool.modules.pools.service import PoolService

    return PoolService(
        DbClock(),
        PostgresAuditLog(),
        PostgresJobQueue(),
        BeaconAnnouncement(
            mode=settings.beacon_mode,
            base_url=settings.drand_base_url,
            chain_hash=settings.drand_chain_hash,
        ),
    )


def checkout_engine(settings: Settings):
    """The single transition engine instance: one set of platform ports (I10)."""
    from fairpool.infra.audit import PostgresAuditLog
    from fairpool.infra.clock import DbClock
    from fairpool.infra.idempotency import PostgresIdempotencyStore
    from fairpool.infra.jobs import PostgresJobQueue
    from fairpool.modules.checkout.engine import CheckoutEngine
    from fairpool.modules.ledger.service import PostgresLedger
    from fairpool.modules.notify.service import PostgresNotifier

    return CheckoutEngine(
        clock=DbClock(),
        audit=PostgresAuditLog(),
        jobs=PostgresJobQueue(),
        ledger=PostgresLedger(),
        notifier=PostgresNotifier(),
        idempotency=PostgresIdempotencyStore(),
    )


def worker_handlers(settings: Settings):
    """Only the kinds Phase 3 actually implements (T03A02, T03B02, T03B04).

    Everything else stays PENDING and unclaimed on purpose: an enqueue is not
    evidence that work happened, and registering a half-handler would let a queue
    look like a feature.
    """
    from fairpool.infra.audit import PostgresAuditLog
    from fairpool.infra.clock import DbClock
    from fairpool.infra.jobs import PostgresJobQueue
    from fairpool.modules.checkout.expiry import OfferExpiry
    from fairpool.modules.notify.service import PostgresNotifier
    from fairpool.modules.pools.close import PoolCloseService
    from fairpool.modules.search.handlers import search_index_handler
    from fairpool.modules.search.indexer import build_search_indexer

    clock, audit, jobs = DbClock(), PostgresAuditLog(), PostgresJobQueue()
    expiry = OfferExpiry(engine=checkout_engine(settings), jobs=jobs)
    close = PoolCloseService(
        clock, audit, jobs, PostgresNotifier(), payment_mode=settings.payment_mode
    )
    return {
        "pool.open": pool_service(settings).open,
        "pool.close": close.close,
        "offer.expire": expiry.expire,
        "search.index": search_index_handler(build_search_indexer(settings)),
    }


def ai_client(settings: Settings):
    from fairpool.adapters.ai.client import AIUnavailable, GeminiAI
    from fairpool.modules.intake.run_log import PostgresAiRunLogger

    if not settings.ai_enabled:
        raise AIUnavailable("AI_DISABLED")
    return GeminiAI(
        api_key=settings.gemini_api_key.get_secret_value(),
        model_parse=settings.ai_model_parse,
        model_sim=settings.ai_model_sim,
        logger=PostgresAiRunLogger(),
    )
