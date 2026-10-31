"""Pool lifecycle, frozen public rules and transactional publication."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import Pool
from fairpool.db.models.enums import PoolMode, PoolStatus
from fairpool.domain.errors import ApplicationError
from fairpool.domain.hashing import rules_hash
from fairpool.domain.pool_config import PoolInput
from fairpool.domain.states import assert_transition
from fairpool.ports import AuditLog, BeaconClient, Clock, JobQueue


def rules_document(pool: Pool) -> dict[str, Any]:
    return dict(
        v=1,
        pool_id=str(pool.id),
        rule_version=pool.rule_version,
        template=pool.template,
        lot_plan=pool.lot_plan,
        timeline=pool.timeline,
        require_paypal_link=pool.require_paypal_link,
        allocation="seeded_lottery_v1",
        bid_ranking="ranking_v1",
        refill={"max_refill_waves": pool.timeline["max_refill_waves"]},
        beacon={
            key: pool.beacon[key]
            for key in ("source", "chain_hash", "round")
            if pool.beacon and key in pool.beacon
        },
        disclosures={"lots_may_differ": True},
    )


def summary(pool: Pool) -> dict[str, Any]:
    lots = [lot for zone in pool.lot_plan for lot in zone["lots"]]
    return dict(
        pool_id=pool.id,
        title=pool.title,
        status=pool.status,
        mode=pool.mode,
        product_key=pool.template["product_key"],
        variant=pool.template.get("variant"),
        condition=pool.template["condition"],
        zone_ids=[z["zone_id"] for z in pool.lot_plan],
        seats=sum(x["seats"] for x in lots),
        min_seats=sum(x["min_seats"] for x in lots),
        close_at=pool.timeline["close_at"],
    )


class PoolService:
    def __init__(self, clock: Clock, audit: AuditLog, jobs: JobQueue, beacon: BeaconClient) -> None:
        self.clock, self.audit, self.jobs, self.beacon = clock, audit, jobs, beacon

    async def _get(self, session: AsyncSession, pool_id: UUID) -> Pool:
        pool = await session.scalar(select(Pool).where(Pool.id == pool_id).with_for_update())
        if pool is None:
            raise ApplicationError("NOT_FOUND")
        return pool

    async def _transition(self, session: AsyncSession, pool: Pool, status: str, actor: str) -> None:
        assert_transition("pool", str(pool.status), status)
        before = str(pool.status)
        pool.status = PoolStatus(status)
        await session.flush()
        await self.audit.append(
            session,
            actor=actor,
            action=f"pool.{status.lower()}",
            subject_type="pool",
            subject_id=str(pool.id),
            payload={"from": before, "to": status, "rules_hash": pool.rules_hash},
        )

    async def create(self, session: AsyncSession, *, actor_id: UUID, payload: PoolInput) -> Pool:
        now = await self.clock.db_now(session)
        if payload.timeline.open_at < now:
            raise ApplicationError("VALIDATION_ERROR")
        timeline = payload.timeline.model_dump(mode="json")
        for key in ("open_at", "close_at"):
            timeline[key] = getattr(payload.timeline, key).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        template = payload.template.model_dump(mode="json")
        pool = Pool(
            id=uuid4(),
            mode=PoolMode.LIVE_SANDBOX,
            status=PoolStatus.DRAFT,
            title=payload.title,
            template=template,
            lot_plan=[x.model_dump() for x in payload.lot_plan],
            timeline=timeline,
            require_paypal_link=payload.require_paypal_link,
            rule_version=payload.rule_version,
            created_by=actor_id,
            search_text=" ".join(
                [
                    payload.title,
                    template["product_key"],
                    template["variant"] or "",
                    template["condition"],
                    *template["bundle_contents"],
                    *[r for z in template["zones"] for r in z["regions"]],
                ]
            ),
        )
        session.add(pool)
        await session.flush()
        await self.audit.append(
            session,
            actor=str(actor_id),
            action="pool.create",
            subject_type="pool",
            subject_id=str(pool.id),
            payload={},
        )
        return pool

    async def publish(self, session: AsyncSession, pool_id: UUID, *, actor_id: UUID) -> Pool:
        pool = await self._get(session, pool_id)
        if pool.status != PoolStatus.DRAFT:
            raise ApplicationError("ORDER_STATE_INVALID")
        now = await self.clock.db_now(session)
        close = datetime.fromisoformat(pool.timeline["close_at"].replace("Z", "+00:00"))
        opens = datetime.fromisoformat(pool.timeline["open_at"].replace("Z", "+00:00"))
        if opens < now or close <= now:
            raise ApplicationError("POOL_CLOSED")
        pool.beacon = await self.beacon.announce(
            close_at=close, delay_s=pool.timeline["beacon_delay_s"]
        )
        pool.rules_hash = rules_hash(rules_document(pool))
        pool.published_at = now
        await self._transition(session, pool, "PUBLISHED", str(actor_id))
        for kind, at in (("pool.open", opens), ("pool.close", close), ("search.index", now)):
            await self.jobs.enqueue(
                session,
                kind,
                {"pool_id": str(pool.id), "doc_kind": "pool", "doc_id": str(pool.id)},
                run_at=at,
                concurrency_key=f"pool:{pool.id}",
                dedupe_key=f"{kind}:{pool.id}",
            )
        return pool

    async def cancel(self, session: AsyncSession, pool_id: UUID, *, actor_id: UUID) -> Pool:
        pool = await self._get(session, pool_id)
        if await session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM buyer_orders b JOIN lots l ON l.id=b.lot_id "
                "WHERE l.pool_id=:id)"
            ),
            {"id": pool_id},
        ):
            raise ApplicationError("ORDER_STATE_INVALID")
        await self._transition(session, pool, "CANCELLED", str(actor_id))
        return pool

    async def open(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        pool = await self._get(session, UUID(payload["pool_id"]))
        if pool.status != PoolStatus.PUBLISHED:
            return
        now = await self.clock.db_now(session)
        opens = datetime.fromisoformat(pool.timeline["open_at"].replace("Z", "+00:00"))
        close = datetime.fromisoformat(pool.timeline["close_at"].replace("Z", "+00:00"))
        if opens <= now < close:
            await self._transition(session, pool, "OPEN", "worker")
