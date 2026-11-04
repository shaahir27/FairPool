"""Ops console read models and the lot abort (T07A04; FR-OP-01, api.md admin).

Every lot status change here goes through ``apply_lot_transition`` -- the same
whitelist check, audit row and follow-up jobs the checkout handlers use (I10).
``abort`` has exactly two shapes:

* an AWARDED lot before checkout opens is cancelled (LS-13) and nothing is
  enqueued, because no offer, authorization or capture exists yet (N3);
* a live lot (CHECKOUT_OPEN or FUNDING) enters FAILING through LS-08 or LS-09 --
  their guards name "ops abort" as one of the ways in -- and hands the lot to the
  ``lot.finalize_fail`` job, which voids and refunds to net zero (LS-10).

The rest of this module is derived read-only data: the lot view for the console,
the alert list and the audit-chain export. None of it decides a transition.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.auction import Award
from fairpool.db.models.pools import Lot
from fairpool.domain.errors import ApplicationError
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.checkout import mock_gateway
from fairpool.modules.checkout.funding import apply_lot_transition, lock_lot
from fairpool.ports import Notifier

#: A FAILING lot gets this long to reach FAILED_CLOSED before the console's
#: "beyond one sweep" alert names it (the failure handler re-checks every 10 s).
FAILING_GRACE_S: Final[int] = 300

#: Abort leaves a lot alone when it is already on a terminal or failing path.
ABORT_NOOP_STATUSES: Final[frozenset[str]] = frozenset({"FAILING", "FAILED_CLOSED", "CANCELLED"})


async def lot_view(session: AsyncSession, lot_id: UUID) -> dict[str, Any]:
    """The declared ``AdminLotView`` plus the money facts an operator needs."""
    lot = (
        await session.execute(
            text(
                "SELECT id, pool_id, status::text, seats, min_seats, award_id, "
                "payment_router::text, payment_mode::text FROM lots WHERE id = :lot"
            ),
            {"lot": lot_id},
        )
    ).first()
    if lot is None:
        raise ApplicationError("NOT_FOUND")

    order_rows = (
        await session.execute(
            text(
                "SELECT status::text, count(*) FROM buyer_orders "
                "WHERE lot_id = :lot GROUP BY status ORDER BY status::text"
            ),
            {"lot": lot_id},
        )
    ).all()
    captures = await _resource_totals(session, "paypal_captures", lot_id)
    refunds = await _resource_totals(session, "paypal_refunds", lot_id)
    ledger = await session.execute(
        text(
            "SELECT count(*), COALESCE(sum(CASE WHEN kind = 'CAPTURE_COMPLETED' "
            "THEN amount_cents WHEN kind = 'REFUND_COMPLETED' THEN -amount_cents "
            "ELSE 0 END), 0) FROM ledger_entries WHERE lot_id = :lot"
        ),
        {"lot": lot_id},
    )
    ledger_count, net_cents = ledger.one()
    dead_letters = (
        await session.execute(
            text(
                "SELECT DISTINCT w.id, w.event_type, w.status::text FROM webhook_events w "
                "WHERE w.status IN ('DEAD_LETTER','REJECTED') AND EXISTS ("
                "  SELECT 1 FROM paypal_orders po "
                "  JOIN buyer_orders bo ON bo.id = po.buyer_order_id "
                "  WHERE bo.lot_id = :lot AND position(po.paypal_order_id IN w.raw_body) > 0"
                ") ORDER BY w.id"
            ),
            {"lot": lot_id},
        )
    ).all()

    return {
        "lot_id": lot.id,
        "pool_id": lot.pool_id,
        "status": lot.status,
        "seats": int(lot.seats),
        "min_seats": int(lot.min_seats),
        "award_id": lot.award_id,
        "payment_router": lot.payment_router,
        "payment_mode": lot.payment_mode,
        "money": {
            "orders_by_status": {str(row[0]): int(row[1]) for row in order_rows},
            "captures": captures,
            "refunds": refunds,
            "ledger": {"entries": int(ledger_count), "net_cents": int(net_cents)},
            "dead_letters": [
                {"event_id": str(row[0]), "event_type": str(row[1]), "status": str(row[2])}
                for row in dead_letters
            ],
        },
    }


async def _resource_totals(session: AsyncSession, table: str, lot_id: UUID) -> dict[str, Any]:
    """Per-status counts and cents for captures or refunds of one lot."""
    # The table name comes from this module's own two literals, never from input.
    if table not in {"paypal_captures", "paypal_refunds"}:
        raise ApplicationError("INTEGRITY_ERROR")
    rows = (
        await session.execute(
            text(
                f"SELECT r.status, count(*), COALESCE(sum(r.amount_cents), 0) FROM {table} r "
                "JOIN buyer_orders bo ON bo.id = r.buyer_order_id "
                "WHERE bo.lot_id = :lot GROUP BY r.status ORDER BY r.status"
            ),
            {"lot": lot_id},
        )
    ).all()
    by_status = {str(row[0]): {"count": int(row[1]), "cents": int(row[2])} for row in rows}
    total = await session.scalar(
        text(
            f"SELECT count(*) FROM {table} r JOIN buyer_orders bo "
            "ON bo.id = r.buyer_order_id WHERE bo.lot_id = :lot"
        ),
        {"lot": lot_id},
    )
    return {"total": int(total or 0), "by_status": by_status}


async def abort(
    session: AsyncSession, *, lot_id: UUID, actor: str, notifier: Notifier | None = None
) -> dict[str, Any]:
    """Abort one lot on the whitelist: LS-13, or LS-08/LS-09 into FAILING."""
    lot = await lock_lot(session, lot_id)
    status = str(lot.status)
    if status in ABORT_NOOP_STATUSES:
        # An abort that already happened is not an error; the console can retry.
        return {"lot_id": str(lot.id), "status": status, "transition_id": None}

    audit = PostgresAuditLog()
    if status == "AWARDED":
        if await _money_exists(session, lot_id):
            raise ApplicationError("ORDER_STATE_INVALID")
        await apply_lot_transition(
            session,
            lot=lot,
            to_status="CANCELLED",
            trigger="admin.abort",
            audit=audit,
            actor=actor,
            payload={"transition_id": "LS-13"},
        )
        await _notify_seated(session, lot=lot, notifier=notifier)
        return {"lot_id": str(lot.id), "status": "CANCELLED", "transition_id": "LS-13"}

    if status in {"CHECKOUT_OPEN", "FUNDING"}:
        transition_id = "LS-08" if status == "CHECKOUT_OPEN" else "LS-09"
        moq = await session.scalar(select(Award.moq).where(Award.lot_id == lot_id))
        if moq is None:
            raise ApplicationError("INTEGRITY_ERROR")
        await apply_lot_transition(
            session,
            lot=lot,
            to_status="FAILING",
            trigger="job:lot.try_fund",
            audit=audit,
            actor=actor,
            payload={"transition_id": transition_id, "moq": int(moq), "aborted": True},
        )
        # The declared follow-up of LS-08/LS-09: the failure handler voids and
        # refunds, then closes the lot at net zero (LS-10).
        await PostgresJobQueue().enqueue(
            session,
            "lot.finalize_fail",
            {"lot_id": str(lot.id)},
            concurrency_key=f"lot:{lot.id}",
            dedupe_key=f"finalize_fail:{lot.id}",
        )
        return {"lot_id": str(lot.id), "status": "FAILING", "transition_id": transition_id}

    # AWARDED, CHECKOUT_OPEN and FUNDING are the only abortable states (LS-13,
    # LS-08 and LS-09); anything else keeps the state the machine gave it.
    raise ApplicationError("ORDER_STATE_INVALID")


async def _money_exists(session: AsyncSession, lot_id: UUID) -> bool:
    """LS-13's "no money exists": no live authorization, capture or ledger fact (N3)."""
    found = await session.scalar(
        text(
            "SELECT 1 FROM paypal_authorizations pa JOIN buyer_orders bo "
            "ON bo.id = pa.buyer_order_id WHERE bo.lot_id = :lot "
            "AND pa.status IN ('CREATED','PENDING') "
            "UNION ALL SELECT 1 FROM paypal_captures pc JOIN buyer_orders bo "
            "ON bo.id = pc.buyer_order_id WHERE bo.lot_id = :lot "
            "AND pc.status IN ('COMPLETED','PENDING') "
            "UNION ALL SELECT 1 FROM ledger_entries le WHERE le.lot_id = :lot LIMIT 1"
        ),
        {"lot": lot_id},
    )
    return found is not None


async def _notify_seated(session: AsyncSession, *, lot: Lot, notifier: Notifier | None) -> None:
    """LS-13's notify effect: every seated buyer learns the lot was cancelled."""
    if notifier is None:
        # The caller owns the notifier port; without one the audit still records
        # the cancellation and nothing claims a buyer was told.
        return
    user_ids = (
        (
            await session.execute(
                text(
                    "SELECT DISTINCT pe.user_id FROM allocations a "
                    "JOIN pool_entries pe ON pe.id = a.entry_id "
                    "WHERE a.lot_id = :lot AND a.status = 'SEATED'"
                ),
                {"lot": lot.id},
            )
        )
        .scalars()
        .all()
    )
    for user_id in user_ids:
        await notifier.notify(
            session,
            user_id=user_id,
            kind="lot.cancelled",
            payload={"lot_id": str(lot.id), "pool_id": str(lot.pool_id)},
        )


async def alerts(
    session: AsyncSession, *, failing_grace_s: int = FAILING_GRACE_S
) -> dict[str, Any]:
    """Derived rows an operator must see; read-only and bounded."""
    rows: list[dict[str, Any]] = []

    dead = (
        await session.execute(
            text(
                "SELECT id, paypal_event_id, event_type, status::text, received_at "
                "FROM webhook_events WHERE status IN ('DEAD_LETTER','REJECTED') "
                "ORDER BY received_at, id LIMIT 200"
            )
        )
    ).all()
    for event_id, paypal_event_id, event_type, status, received_at in dead:
        rows.append(
            {
                "kind": "webhook_dead_letter",
                "event_id": str(event_id),
                "paypal_event_id": str(paypal_event_id),
                "event_type": str(event_type),
                "status": str(status),
                "received_at": received_at.isoformat(),
            }
        )

    overdue = (
        await session.execute(
            text(
                "SELECT id, pool_id, fund_deadline_at FROM lots "
                "WHERE status = 'CHECKOUT_OPEN' AND fund_deadline_at IS NOT NULL "
                "AND fund_deadline_at < now() ORDER BY fund_deadline_at, id LIMIT 200"
            )
        )
    ).all()
    for lot_id, pool_id, deadline in overdue:
        rows.append(
            {
                "kind": "lot_past_fund_deadline",
                "lot_id": str(lot_id),
                "pool_id": str(pool_id),
                "fund_deadline_at": deadline.isoformat(),
            }
        )

    # The age guard is a timeline value (72 h at most); a MISSING authorization GET
    # is not required to raise this: the row's own age past the guard is the fact.
    aged = (
        await session.execute(
            text(
                "SELECT bo.id, pa.paypal_auth_id, "
                "EXTRACT(EPOCH FROM (now() - pa.created_at))::bigint AS age_s "
                "FROM paypal_authorizations pa "
                "JOIN buyer_orders bo ON bo.id = pa.buyer_order_id "
                "JOIN lots l ON l.id = bo.lot_id "
                "JOIN pools p ON p.id = l.pool_id "
                "WHERE pa.status = 'CREATED' "
                "AND bo.status IN ('AUTHORIZING','AUTHORIZED') "
                "AND now() - pa.created_at >= make_interval(secs => COALESCE("
                "(p.timeline ->> 'authorization_age_guard_s')::double precision, 216000)) "
                "ORDER BY pa.created_at, pa.id LIMIT 200"
            )
        )
    ).all()
    for buyer_order_id, paypal_auth_id, age_s in aged:
        rows.append(
            {
                "kind": "authorization_aged",
                "buyer_order_id": str(buyer_order_id),
                "paypal_auth_id": str(paypal_auth_id),
                "age_s": int(age_s),
            }
        )

    failing = (
        await session.execute(
            text(
                "SELECT l.id, l.pool_id, "
                "COALESCE(max(a.created_at), l.created_at) AS since "
                "FROM lots l LEFT JOIN audit_log a ON a.subject_type = 'lot' "
                "AND a.subject_id = l.id::text AND a.action = 'lot.failing' "
                "WHERE l.status = 'FAILING' "
                "GROUP BY l.id, l.pool_id, l.created_at "
                "HAVING COALESCE(max(a.created_at), l.created_at) "
                "<= now() - make_interval(secs => :grace) "
                "ORDER BY l.id LIMIT 200"
            ),
            {"grace": int(failing_grace_s)},
        )
    ).all()
    for lot_id, pool_id, since in failing:
        rows.append(
            {
                "kind": "lot_failing",
                "lot_id": str(lot_id),
                "pool_id": str(pool_id),
                "failing_since": since.isoformat(),
            }
        )

    return {"alerts": rows, "count": len(rows)}


async def audit_export(session: AsyncSession, since_seq: int = 0) -> list[dict[str, Any]]:
    """The chained audit rows after ``since_seq``, with their own hashes."""
    rows = (
        await session.execute(
            text(
                "SELECT seq, prev_hash, hash, actor, action, subject_type, subject_id, "
                "payload, created_at FROM audit_log WHERE seq > :since ORDER BY seq LIMIT 10000"
            ),
            {"since": int(since_seq)},
        )
    ).all()
    return [
        {
            "seq": int(row.seq),
            "prev_hash": str(row.prev_hash),
            "hash": str(row.hash),
            "actor": str(row.actor),
            "action": str(row.action),
            "subject_type": str(row.subject_type),
            "subject_id": None if row.subject_id is None else str(row.subject_id),
            "payload": dict(row.payload),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def mock_toggle(kind: str, value: str | None, ttl_s: int, *, enabled: bool) -> dict[str, Any]:
    """Arm one demo toggle, or ``FEATURE_DISABLED`` when the gate is off."""
    mock_gateway.set_toggle(kind=kind, value=value, ttl_s=ttl_s, enabled=enabled)
    return {"kind": kind, "value": value, "ttl_s": int(ttl_s), "labels": [mock_gateway.MOCK_LABEL]}


def mock_reset(*, enabled: bool) -> dict[str, Any]:
    """Clear every demo toggle; the ordinary path is never gated."""
    if not enabled:
        raise ApplicationError("FEATURE_DISABLED")
    mock_gateway.reset()
    return {"labels": [], "active": []}
