"""Consented demand signals become a proposed pool (CR-17, FR-DM-01 to FR-DM-06).

The split that keeps the invariants intact: buyers consent to a signal, deterministic
rules decide when a cluster has enough distinct people, the sweep creates a **DRAFT**
pool through the ordinary ``PoolService``, and a human publishes it through the ordinary
publication path. So a demand-formed pool has the same frozen rules, beacon, seed,
commitments and audit chain as an operator-created one -- nothing about fairness is
special-cased, and no model ever decides that a pool exists.

Notifications are in-app only (FR-UI-09) and are written inside the same transaction as
the transition they describe (I10). A signal carries no cap, no message and no address.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import Pool
from fairpool.db.models.demand import DemandCluster, DemandSignal
from fairpool.domain.demand import cluster_key, cluster_title
from fairpool.domain.errors import ApplicationError
from fairpool.domain.pool_config import (
    TIMING_PROFILES,
    LotSize,
    PoolInput,
    Template,
    Timeline,
    Zone,
    ZonePlan,
)
from fairpool.modules.notify.service import PostgresNotifier
from fairpool.modules.pools.service import PoolService
from fairpool.ports import AuditLog, Clock, JobQueue

#: Published formation rule: a cluster needs this many distinct active signals.
DEFAULT_THRESHOLD = 5
DEFAULT_SIGNAL_TTL_DAYS = 30
_VISIBLE = ("COLLECTING", "PROPOSED", "POOLED")


class DemandService:
    def __init__(
        self,
        *,
        clock: Clock,
        audit: AuditLog,
        notifier: PostgresNotifier,
        pools: PoolService,
        jobs: JobQueue,
        threshold: int = DEFAULT_THRESHOLD,
        signal_ttl_days: int = DEFAULT_SIGNAL_TTL_DAYS,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.notifier = notifier
        self.pools = pools
        self.jobs = jobs
        self.threshold = threshold
        self.signal_ttl_days = signal_ttl_days

    # ------------------------------------------------------------- buyer side

    async def signal(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        product_key: str,
        condition: str,
        variant: str | None,
        bundle_contents: list[str],
        region: str,
        source: str,
    ) -> DemandSignal:
        """Record one buyer's consented interest; a repeat ask returns the same row."""
        try:
            key = cluster_key(
                product_key=product_key,
                condition=condition,
                variant=variant,
                bundle_contents=bundle_contents,
            )
        except ValueError:
            raise ApplicationError("VALIDATION_ERROR") from None
        # A missing cluster has no row to lock; serialize its first signals too.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"demand:{key}"},
        )
        now = await self.clock.db_now(session)
        cluster = await session.scalar(
            select(DemandCluster).where(DemandCluster.cluster_key == key).with_for_update()
        )
        features = {
            "condition": condition,
            "variant": variant,
            "bundle": sorted(bundle_contents),
        }
        if cluster is None:
            cluster = DemandCluster(
                cluster_key=key,
                product_key=product_key,
                title=cluster_title(product_key=product_key, variant=variant, condition=condition),
                features=features,
                regions=[region],
                status="COLLECTING",
                threshold=self.threshold,
            )
            session.add(cluster)
            await session.flush()
        elif region not in cluster.regions:
            cluster.regions = sorted([*cluster.regions, region])
            await session.flush()

        existing = await session.scalar(
            select(DemandSignal).where(
                DemandSignal.user_id == user_id,
                DemandSignal.cluster_key == key,
                DemandSignal.cancelled_at.is_(None),
            )
        )
        if existing is not None and existing.expires_at > now:
            return existing
        row = existing or DemandSignal(
            id=uuid4(),
            user_id=user_id,
            cluster_key=key,
            region=region,
            source=source,
            expires_at=now + timedelta(days=self.signal_ttl_days),
        )
        row.expires_at = now + timedelta(days=self.signal_ttl_days)
        session.add(row)
        await session.flush()
        await self.audit.append(
            session,
            actor=str(user_id),
            action="demand.signal",
            subject_type="demand_cluster",
            subject_id=key,
            payload={"region": region, "source": source},
        )
        return row

    async def interests(self, session: AsyncSession, *, user_id: UUID) -> list[dict[str, Any]]:
        now = await self.clock.db_now(session)
        rows = await session.execute(
            select(DemandSignal, DemandCluster)
            .join(DemandCluster, DemandCluster.cluster_key == DemandSignal.cluster_key)
            .where(
                DemandSignal.user_id == user_id,
                DemandSignal.cancelled_at.is_(None),
                DemandSignal.expires_at > now,
            )
            .order_by(DemandSignal.created_at, DemandSignal.id)
        )
        return [
            self._interest_view(
                signal, cluster, await self._count(session, cluster.cluster_key, now)
            )
            for signal, cluster in rows
        ]

    async def view(self, session: AsyncSession, *, signal: DemandSignal) -> dict[str, Any]:
        """The buyer's own view of one signal, including the cluster's current count."""
        cluster = await self._cluster(session, signal.cluster_key)
        now = await self.clock.db_now(session)
        return self._interest_view(
            signal, cluster, await self._count(session, cluster.cluster_key, now)
        )

    @staticmethod
    def _interest_view(
        signal: DemandSignal, cluster: DemandCluster, interested: int
    ) -> dict[str, Any]:
        return {
            "signal_id": signal.id,
            "cluster_key": cluster.cluster_key,
            "title": cluster.title,
            "status": cluster.status,
            "pool_id": cluster.pool_id,
            "interested": interested,
            "threshold": cluster.threshold,
            "expires_at": signal.expires_at,
        }

    async def cancel(
        self, session: AsyncSession, *, user_id: UUID, signal_id: UUID
    ) -> DemandSignal:
        row = await session.scalar(
            select(DemandSignal)
            .where(DemandSignal.id == signal_id, DemandSignal.user_id == user_id)
            .with_for_update()
        )
        if row is None:
            raise ApplicationError("NOT_FOUND")
        if row.cancelled_at is None:
            row.cancelled_at = await self.clock.db_now(session)
            await session.flush()
            await self.audit.append(
                session,
                actor=str(user_id),
                action="demand.cancelled",
                subject_type="demand_cluster",
                subject_id=row.cluster_key,
                payload={},
            )
        return row

    # ------------------------------------------------------------ public side

    async def forming(self, session: AsyncSession, *, limit: int = 20) -> list[dict[str, Any]]:
        """Aggregate counts only: no buyer identity, cap or message ever leaves here."""
        now = await self.clock.db_now(session)
        clusters = list(
            await session.scalars(
                select(DemandCluster)
                .where(DemandCluster.status.in_(_VISIBLE))
                .order_by(DemandCluster.created_at, DemandCluster.cluster_key)
                .limit(limit)
            )
        )
        return [
            {
                "cluster_key": cluster.cluster_key,
                "title": cluster.title,
                "product_key": cluster.product_key,
                "condition": cluster.features["condition"],
                "variant": cluster.features.get("variant"),
                "bundle_contents": cluster.features["bundle"],
                "regions": list(cluster.regions),
                "interested": await self._count(session, cluster.cluster_key, now),
                "threshold": cluster.threshold,
                "status": cluster.status,
            }
            for cluster in clusters
        ]

    async def _count(self, session: AsyncSession, key: str, now: Any) -> int:
        return int(
            await session.scalar(
                select(func.count(func.distinct(DemandSignal.user_id))).where(
                    DemandSignal.cluster_key == key,
                    DemandSignal.cancelled_at.is_(None),
                    DemandSignal.expires_at > now,
                )
            )
            or 0
        )

    # ---------------------------------------------------------- formation

    async def sweep(self, session: AsyncSession) -> int:
        """Propose a draft pool for every cluster that reached its published threshold."""
        now = await self.clock.db_now(session)
        clusters = list(
            await session.scalars(
                select(DemandCluster)
                .where(DemandCluster.status == "COLLECTING")
                .order_by(DemandCluster.created_at, DemandCluster.cluster_key)
                .with_for_update()
            )
        )
        proposed = 0
        for cluster in clusters:
            distinct = await self._count(session, cluster.cluster_key, now)
            if distinct < cluster.threshold:
                continue
            pool = await self.pools.create(
                session,
                actor_id=await self._formation_actor(session),
                payload=self._pool_input(cluster, now=now, distinct=distinct),
            )
            cluster.status = "PROPOSED"
            cluster.pool_id = pool.id
            cluster.proposed_at = now
            await session.flush()
            await self.audit.append(
                session,
                actor="system",
                action="demand.proposed",
                subject_type="demand_cluster",
                subject_id=cluster.cluster_key,
                payload={"pool_id": str(pool.id), "interested": distinct},
            )
            await self._notify(session, cluster, kind="demand.pool_proposed", interested=distinct)
            proposed += 1
        return proposed

    async def _formation_actor(self, session: AsyncSession) -> UUID:
        """The bookkeeping owner of a demand-formed pool, as ``sim.store`` does for its own.

        ``pools.created_by`` is NOT NULL. This row is not a participant: it never joins,
        never bids and cannot sign in, because its password hash is not a hash.
        """
        actor = uuid5(NAMESPACE_URL, "fairpool:demand-formation-rule")
        await session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, role, display_name) "
                "VALUES (:id, 'demand-rule@fairpool.invalid', 'demand-rule-only', "
                "'admin'::user_role, 'Demand formation rule') "
                "ON CONFLICT DO NOTHING"
            ),
            {"id": actor},
        )
        return actor

    def _pool_input(self, cluster: DemandCluster, *, now: Any, distinct: int) -> PoolInput:
        """Published defaults for a demand-formed pool, identical for every cluster."""
        opens = now + timedelta(hours=1)
        closes = opens + timedelta(days=7)
        regions = sorted(set(cluster.regions)) or ["NY"]
        return PoolInput(
            title=cluster.title,
            template=Template(
                product_key=cluster.product_key[:200],
                variant=(cluster.features.get("variant") or None),
                title=cluster.title,
                condition=cluster.features["condition"],
                quantity=1,
                currency="USD",
                bundle_contents=cluster.features["bundle"],
                delivery_sla_days=7,
                fund_by=(closes + timedelta(days=14)).date().isoformat(),
                min_return_days=14,
                zones=[Zone(zone_id="US", label="United States", regions=regions)],
            ),
            lot_plan=[
                ZonePlan(
                    zone_id="US",
                    lots=[
                        LotSize(seats=max(distinct, cluster.threshold), min_seats=cluster.threshold)
                    ],
                )
            ],
            timeline=Timeline(open_at=opens, close_at=closes, **TIMING_PROFILES["prodlike"]),
            require_paypal_link=True,
        )

    async def _notify(
        self, session: AsyncSession, cluster: DemandCluster, *, kind: str, interested: int
    ) -> None:
        now = await self.clock.db_now(session)
        holders = list(
            await session.scalars(
                select(DemandSignal.user_id)
                .where(
                    DemandSignal.cluster_key == cluster.cluster_key,
                    DemandSignal.cancelled_at.is_(None),
                    DemandSignal.expires_at > now,
                )
                .distinct()
            )
        )
        for user_id in holders:
            await self.notifier.notify(
                session,
                user_id=user_id,
                kind=kind,
                payload={
                    "cluster_key": cluster.cluster_key,
                    "title": cluster.title,
                    "pool_id": str(cluster.pool_id) if cluster.pool_id else None,
                    "interested": interested,
                    "threshold": cluster.threshold,
                },
            )
        await session.execute(
            update(DemandSignal)
            .where(
                DemandSignal.cluster_key == cluster.cluster_key,
                DemandSignal.cancelled_at.is_(None),
            )
            .values(notified_at=now)
        )

    # --------------------------------------------------------- operator side

    async def proposals(self, session: AsyncSession) -> list[dict[str, Any]]:
        now = await self.clock.db_now(session)
        clusters = list(
            await session.scalars(
                select(DemandCluster)
                .where(DemandCluster.status.in_(("PROPOSED", "POOLED", "REJECTED")))
                .order_by(DemandCluster.proposed_at, DemandCluster.cluster_key)
            )
        )
        return [
            {
                "cluster_key": cluster.cluster_key,
                "title": cluster.title,
                "status": cluster.status,
                "pool_id": cluster.pool_id,
                "regions": list(cluster.regions),
                "interested": await self._count(session, cluster.cluster_key, now),
                "threshold": cluster.threshold,
                "proposed_at": cluster.proposed_at,
            }
            for cluster in clusters
        ]

    async def _cluster(self, session: AsyncSession, key: str) -> DemandCluster:
        cluster = await session.scalar(
            select(DemandCluster).where(DemandCluster.cluster_key == key).with_for_update()
        )
        if cluster is None:
            raise ApplicationError("NOT_FOUND")
        return cluster

    async def publish(self, session: AsyncSession, *, cluster_key: str, actor_id: UUID) -> Pool:
        cluster = await self._cluster(session, cluster_key)
        if cluster.status != "PROPOSED" or cluster.pool_id is None:
            raise ApplicationError("ORDER_STATE_INVALID")
        pool = await self.pools.publish(session, cluster.pool_id, actor_id=actor_id)
        now = await self.clock.db_now(session)
        cluster.status = "POOLED"
        cluster.pooled_at = now
        await session.flush()
        await self.audit.append(
            session,
            actor=str(actor_id),
            action="demand.published",
            subject_type="demand_cluster",
            subject_id=cluster.cluster_key,
            payload={"pool_id": str(pool.id)},
        )
        await self._notify(
            session,
            cluster,
            kind="demand.pool_open",
            interested=await self._count(session, cluster.cluster_key, now),
        )
        return pool

    async def reject(
        self, session: AsyncSession, *, cluster_key: str, actor_id: UUID
    ) -> DemandCluster:
        cluster = await self._cluster(session, cluster_key)
        if cluster.status != "PROPOSED":
            raise ApplicationError("ORDER_STATE_INVALID")
        if cluster.pool_id is not None:
            await self.pools.cancel(session, cluster.pool_id, actor_id=actor_id)
        cluster.status = "REJECTED"
        await session.flush()
        await self.audit.append(
            session,
            actor=str(actor_id),
            action="demand.rejected",
            subject_type="demand_cluster",
            subject_id=cluster.cluster_key,
            payload={},
        )
        return cluster
