"""Composition root: select simulation before constructing network dependencies.

``checkout_services`` builds every checkout dependency exactly once -- one engine,
one allocation read service, one merchant directory, one router over one gateway --
and both the HTTP routes and the worker handlers use those objects. That is what
makes a test that counts calls on them count the real ones (T04X01, IT-4).

``worker_handlers`` registers the kinds Phase 4 actually implements and nothing
else. Everything else stays PENDING and unclaimed on purpose: an enqueue is not
evidence that work happened, and registering a half-handler would let a queue look
like a feature (``domain-ports.md`` section 5, CR-3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from fairpool.adapters.paypal import routers as paypal_routers
from fairpool.adapters.paypal.gateway import RestPayPalGateway
from fairpool.adapters.paypal.identity import RestPayPalIdentity
from fairpool.config import Settings
from fairpool.domain.errors import ApplicationError
from fairpool.domain.payments import Payee
from fairpool.fakes.payments import FakePayPalGateway
from fairpool.ports import AwardView, PayeeRef, PayPalIdentity


def paypal_identity(settings: Settings) -> PayPalIdentity:
    return RestPayPalIdentity(settings)


if TYPE_CHECKING:
    from fairpool.infra.crypto import AesGcmCipher
    from fairpool.modules.allocation.read_service import PostgresAllocationRead
    from fairpool.modules.checkout.authorize import CheckoutAuthorizeHandlers
    from fairpool.modules.checkout.engine import CheckoutEngine
    from fairpool.modules.checkout.failure import FailureService
    from fairpool.modules.checkout.funding import FundingService
    from fairpool.modules.checkout.open_checkout import OpenCheckoutHandler
    from fairpool.modules.checkout.refill import RefillService
    from fairpool.modules.checkout.shipping import ShippingCipher
    from fairpool.modules.checkout.vault_charge import VaultChargeHandler
    from fairpool.modules.merchants.directory import PostgresMerchantDirectory

#: ``domain-ports.md`` section 5 kinds this phase implements, in registration order.
#: A kind is here because its handler exists, and a handler is registered because
#: its kind is here: ``tests/unit/test_worker_registry.py`` proves both directions.
IMPLEMENTED_JOB_KINDS: Final[frozenset[str]] = frozenset(
    {
        "pool.open",
        "pool.close",
        "pool.seed",
        "pool.allocate",
        "search.index",
        "lot.bid_open",
        "lot.bid_close",
        "lot.award",
        "lot.open_checkout",
        "offer.expire",
        "order.vault_charge",
        "order.authorize",
        "order.capture",
        "capture.poll",
        "lot.try_fund",
        "lot.refill",
        "lot.finalize_close",
        "lot.finalize_fail",
        "void.run",
        "refund.run",
        "order.resolve",
        "reconciler.sweep",
        "webhook.process",
        "shipments.submit",
    }
)


@dataclass
class PaymentRouter:
    name: str
    # A concrete union of gateway classes cannot be passed where a handler protocol
    # declares a narrower ``gateway`` attribute, because mutable attributes are
    # invariant; each handler re-types its own view of this object.
    gateway: Any
    seller: Payee

    def payee_for(self, award: AwardView, payee_ref: PayeeRef) -> Payee:
        return self.seller

    def label(self) -> str | None:
        # One registry owns the sentence (T07A03); no copy lives here any more.
        return paypal_routers.label(self.name)


def payment_router(
    settings: Settings, *, simulated: bool = False, fake_outcome: str = "completed"
) -> PaymentRouter:
    if simulated or settings.payment_router == "fake":
        router = PaymentRouter(
            "fake", FakePayPalGateway(outcome=fake_outcome), Payee("fake@example.test", None)
        )
    else:
        # ``payee_email`` and ``platform`` raise NotEnabled (S7, G4, G9).
        spec = paypal_routers.require(settings.payment_router)
        router = PaymentRouter(
            spec.name,
            RestPayPalGateway(settings),
            Payee(settings.single_seller_email, settings.single_seller_merchant_id or None),
        )
    if settings.mock_toggles_enabled:
        # T07A04: the demo wrapper exists only behind the flag; without it no
        # object here can add ``PayPal-Mock-Response`` at all (paypal-adapter.md §10).
        from fairpool.modules.checkout.mock_gateway import FaultInjectingGateway

        router.gateway = FaultInjectingGateway(router.gateway)
    return router


class _VaultKeyMissing:
    """The cipher when ``VAULT_TOKEN_KEY`` is absent.

    ``PAYMENT_MODE=vault_charge`` requires the key (config-and-errors.md), so this
    stands only for the modes where ``order.vault_charge`` is never enqueued. If one
    ever runs anyway, the failure is an allowlisted code, never a plaintext token.
    """

    def open(self, nonce: bytes, ciphertext: bytes) -> str:
        del nonce, ciphertext
        raise ApplicationError("INTERNAL_ERROR")


def shipping_cipher(settings: Settings) -> ShippingCipher:
    """The Fernet address cipher (BD-11), or one that fails only when it is used."""
    from fairpool.modules.checkout.shipping import ShippingCipher

    return ShippingCipher(settings.address_encryption_key.get_secret_value())


def _vault_cipher(settings: Settings) -> AesGcmCipher | _VaultKeyMissing:
    from fairpool.infra.crypto import AesGcmCipher

    if settings.vault_token_key is None:
        return _VaultKeyMissing()
    return AesGcmCipher.from_config_value(settings.vault_token_key.get_secret_value())


def merchant_directory(settings: Settings) -> PostgresMerchantDirectory:
    from fairpool.modules.merchants.directory import PostgresMerchantDirectory

    return PostgresMerchantDirectory(
        payment_router=settings.payment_router,
        single_seller_email=settings.single_seller_email,
        single_seller_merchant_id=settings.single_seller_merchant_id,
    )


@dataclass
class CheckoutServices:
    """Every Phase 4 checkout dependency, built once per process or per app."""

    engine: CheckoutEngine
    allocations: PostgresAllocationRead
    directory: PostgresMerchantDirectory
    router: PaymentRouter
    authorize: CheckoutAuthorizeHandlers
    open_checkout: OpenCheckoutHandler
    refill: RefillService
    funding: FundingService
    failure: FailureService
    vault_charge: VaultChargeHandler


def checkout_services(settings: Settings) -> CheckoutServices:
    from fairpool.infra.audit import PostgresAuditLog
    from fairpool.infra.clock import DbClock
    from fairpool.infra.jobs import PostgresJobQueue
    from fairpool.modules.allocation.read_service import PostgresAllocationRead
    from fairpool.modules.checkout.authorize import CheckoutAuthorizeHandlers
    from fairpool.modules.checkout.failure import FailureService
    from fairpool.modules.checkout.funding import FundingService
    from fairpool.modules.checkout.open_checkout import OpenCheckoutHandler
    from fairpool.modules.checkout.refill import RefillService
    from fairpool.modules.checkout.vault_charge import VaultChargeHandler
    from fairpool.modules.ledger.service import PostgresLedger
    from fairpool.modules.notify.service import PostgresNotifier

    engine = checkout_engine(settings)
    allocations = PostgresAllocationRead()
    directory = merchant_directory(settings)
    router = payment_router(settings)
    return CheckoutServices(
        engine=engine,
        allocations=allocations,
        directory=directory,
        router=router,
        authorize=CheckoutAuthorizeHandlers(
            engine=engine,
            clock=DbClock(),
            jobs=PostgresJobQueue(),
            allocations=allocations,
            directory=directory,
            router=router,
            hmac_key=settings.hmac_key.get_secret_value(),
            allowed_payer_countries=settings.allowed_payer_countries,
            dedupe_mode=settings.dedupe_mode,
            public_base_url=settings.public_base_url,
            shipping_cipher=shipping_cipher(settings),
            payload_level=settings.paypal_payload_level,
        ),
        open_checkout=OpenCheckoutHandler(
            clock=DbClock(),
            audit=PostgresAuditLog(),
            jobs=PostgresJobQueue(),
            notifier=PostgresNotifier(),
            allocations=allocations,
        ),
        refill=RefillService(
            clock=DbClock(),
            audit=PostgresAuditLog(),
            jobs=PostgresJobQueue(),
            allocations=allocations,
        ),
        funding=FundingService(
            engine=engine,
            clock=DbClock(),
            audit=PostgresAuditLog(),
            jobs=PostgresJobQueue(),
            notifier=PostgresNotifier(),
            ledger=PostgresLedger(),
            allocations=allocations,
            gateway=router.gateway,
            capture_concurrency=settings.capture_concurrency,
            capture_buffer=settings.capture_buffer,
        ),
        failure=FailureService(
            engine=engine,
            clock=DbClock(),
            audit=PostgresAuditLog(),
            jobs=PostgresJobQueue(),
            ledger=PostgresLedger(),
            gateway=router.gateway,
        ),
        vault_charge=VaultChargeHandler(
            engine=engine,
            clock=DbClock(),
            jobs=PostgresJobQueue(),
            allocations=allocations,
            directory=directory,
            router=router,
            cipher=_vault_cipher(settings),
            concurrency=settings.vault_charge_concurrency,
        ),
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


def worker_handlers(settings: Settings, checkout: CheckoutServices | None = None):
    """The kinds in :data:`IMPLEMENTED_JOB_KINDS`, and nothing else.

    ``checkout`` lets a caller share one checkout graph with the worker (IT-4 builds
    it, counts calls on the real services, and passes it here); the worker itself
    builds its own when none is given.
    """
    from fairpool.adapters.beacon.announcement import BeaconAnnouncement
    from fairpool.infra.audit import PostgresAuditLog
    from fairpool.infra.clock import DbClock
    from fairpool.infra.jobs import PostgresJobQueue
    from fairpool.modules.allocation.service import AllocationService
    from fairpool.modules.auction.handlers import LotAuctionHandlers
    from fairpool.modules.checkout.expiry import OfferExpiry
    from fairpool.modules.fulfillment.tracking import ShipmentTracking
    from fairpool.modules.notify.service import PostgresNotifier
    from fairpool.modules.pools.close import PoolCloseService
    from fairpool.modules.pools.seed import PoolSeedService
    from fairpool.modules.pools.service import PoolService
    from fairpool.modules.reconciler.resolve import Reconciler
    from fairpool.modules.search.handlers import search_index_handler
    from fairpool.modules.search.indexer import build_search_indexer
    from fairpool.modules.webhooks.handlers import WebhookProcessor

    clock, audit, jobs = DbClock(), PostgresAuditLog(), PostgresJobQueue()
    notifier = PostgresNotifier()
    beacon = BeaconAnnouncement(
        mode=settings.beacon_mode,
        base_url=settings.drand_base_url,
        chain_hash=settings.drand_chain_hash,
    )
    pools = PoolService(clock, audit, jobs, beacon)
    close = PoolCloseService(clock, audit, jobs, notifier, payment_mode=settings.payment_mode)
    seed = PoolSeedService(clock, audit, jobs, beacon)
    allocation = AllocationService(clock, audit, jobs)
    auction = LotAuctionHandlers(
        clock=clock,
        audit=audit,
        jobs=jobs,
        notifier=notifier,
        payment_router=settings.payment_router,
        payment_mode=settings.payment_mode,
        flat_delivered=settings.bid_pricing_mode == "flat_delivered",
    )
    surface = checkout if checkout is not None else checkout_services(settings)
    expiry = OfferExpiry(engine=surface.engine, jobs=jobs)
    tracking = ShipmentTracking(
        gateway=surface.router.gateway, enabled=settings.shipment_tracking_enabled
    )

    async def resolve_charge(session: Any, buyer_order_id: UUID) -> None:
        """Settle a CAPTURING order by evidence; each handler ignores the other mode.

        The vault handler owns a ``vault_charge`` lot and the funding service the
        authorize ladder, both stamped on the lot at award (N8), so calling both in
        order settles the row exactly once without the reconciler knowing either mode
        (vault-charge.md section 7).
        """
        await surface.vault_charge.reconcile(session, buyer_order_id)
        await surface.funding.reconcile(session, buyer_order_id)

    reconciler = Reconciler(clock=clock, jobs=jobs, resolve_charge=resolve_charge)

    async def sweep(session, payload) -> None:
        await reconciler.sweep(session, payload)

    async def settle_order(session: Any, buyer_order_id: UUID) -> None:
        """A webhook's "read this again": the resolve handler, which owns the GET."""
        await reconciler.resolve(session, {"buyer_order_id": str(buyer_order_id)})

    async def approve_order(session: Any, buyer_order_id: UUID) -> None:
        """``CHECKOUT.ORDER.APPROVED``: the same FR-CK-05 checks the return URL runs."""
        await surface.authorize.approved(session, buyer_order_id=buyer_order_id)

    webhooks = WebhookProcessor(clock=clock, jobs=jobs, settle=settle_order, approve=approve_order)

    return {
        "pool.open": pools.open,
        "pool.close": close.close,
        "pool.seed": seed.seed,
        "pool.allocate": allocation.allocate,
        "search.index": search_index_handler(build_search_indexer(settings)),
        "lot.bid_open": auction.bid_open,
        "lot.bid_close": auction.bid_close,
        "lot.award": auction.award,
        "lot.open_checkout": surface.open_checkout.open,
        "offer.expire": expiry.expire,
        "order.vault_charge": surface.vault_charge.charge,
        "order.authorize": surface.authorize.authorize,
        "order.capture": surface.funding.capture,
        "capture.poll": surface.funding.poll,
        "lot.try_fund": surface.funding.try_fund,
        "lot.refill": surface.refill.refill,
        "lot.finalize_close": surface.funding.finalize_close,
        "lot.finalize_fail": surface.failure.finalize_fail,
        "void.run": surface.failure.run_void,
        "refund.run": surface.failure.run_refund,
        "order.resolve": reconciler.resolve,
        "reconciler.sweep": sweep,
        "webhook.process": webhooks.process,
        "shipments.submit": tracking.submit,
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
