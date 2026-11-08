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
    """The declared ``AdminLotView``; the dead-letter list has its own route."""
    lot = (
        await session.execute(
            text(
                "SELECT l.id, l.pool_id, l.status::text, l.seats, l.min_seats, l.award_id, "
                "l.payment_router::text, l.payment_mode::text, p.title AS pool_title, "
                "p.template->>'title' AS product_title, m.display_name AS merchant_display_name "
                "FROM lots l JOIN pools p ON p.id = l.pool_id "
                "LEFT JOIN awards a ON a.lot_id = l.id "
                "LEFT JOIN merchants m ON m.id = a.merchant_id WHERE l.id = :lot"
            ),
            {"lot": lot_id},
        )
    ).first()
    if lot is None:
        raise ApplicationError("NOT_FOUND")
    return {
        "lot_id": lot.id,
        "pool_id": lot.pool_id,
        "status": lot.status,
        "seats": int(lot.seats),
        "min_seats": int(lot.min_seats),
        "award_id": lot.award_id,
        "payment_router": lot.payment_router,
        "payment_mode": lot.payment_mode,
        "pool_title": lot.pool_title,
        "product_title": lot.product_title,
        "merchant_display_name": lot.merchant_display_name,
    }


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
        if await _money_in_flight(session, lot_id):
            # funding.py waits for these same states before failing a lot; an abort
            # must not close over a capture or an authorize that is still landing.
            raise ApplicationError("ORDER_STATE_INVALID")
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


async def _money_in_flight(session: AsyncSession, lot_id: UUID) -> bool:
    """A PENDING capture or an AUTHORIZING seat still belongs to the provider."""
    found = await session.scalar(
        text(
            "SELECT 1 FROM paypal_captures pc JOIN buyer_orders bo "
            "ON bo.id = pc.buyer_order_id WHERE bo.lot_id = :lot AND pc.status = 'PENDING' "
            "UNION ALL SELECT 1 FROM buyer_orders bo WHERE bo.lot_id = :lot "
            "AND bo.status = 'AUTHORIZING' LIMIT 1"
        ),
        {"lot": lot_id},
    )
    return found is not None


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

    # T09A05 / audit F5: the money two independent records agree on. A lot's completed
    # captures less its completed refunds, from the PayPal rows, must equal the same
    # figure as the ledger's CAPTURE_COMPLETED less REFUND_COMPLETED. Every ledger amount
    # is positive -- ``to_paypal_string`` refuses a negative -- so direction comes from
    # the kind, not the sign. Only ended lots are compared: a lot mid-flight legitimately
    # has captures the ledger has not been told about yet.
    imbalanced = (
        await session.execute(
            text(
                "SELECT l.id AS lot_id, l.pool_id, l.status::text AS status, "
                "captured.net AS captured_net, ledger.net AS ledger_net FROM lots l "
                "CROSS JOIN LATERAL (SELECT "
                "COALESCE((SELECT SUM(pc.amount_cents) FROM paypal_captures pc "
                "JOIN buyer_orders bo ON bo.id = pc.buyer_order_id "
                "WHERE bo.lot_id = l.id AND pc.status = 'COMPLETED'), 0) "
                "- COALESCE((SELECT SUM(pr.amount_cents) FROM paypal_refunds pr "
                "JOIN buyer_orders bo ON bo.id = pr.buyer_order_id "
                "WHERE bo.lot_id = l.id AND pr.status = 'COMPLETED'), 0) AS net) captured "
                "CROSS JOIN LATERAL (SELECT "
                "COALESCE((SELECT SUM(le.amount_cents) FROM ledger_entries le "
                "WHERE le.lot_id = l.id AND le.kind = 'CAPTURE_COMPLETED'), 0) "
                "- COALESCE((SELECT SUM(le.amount_cents) FROM ledger_entries le "
                "WHERE le.lot_id = l.id AND le.kind = 'REFUND_COMPLETED'), 0) AS net) ledger "
                "WHERE l.status IN ('FUNDED','CLOSED','FAILED_CLOSED') "
                "AND captured.net <> ledger.net ORDER BY l.id LIMIT 200"
            )
        )
    ).all()
    for lot_id, pool_id, status, captured_net, ledger_net in imbalanced:
        rows.append(
            {
                "kind": "ledger_imbalance",
                "lot_id": str(lot_id),
                "pool_id": str(pool_id),
                "status": str(status),
                "captured_net_cents": int(captured_net),
                "ledger_net_cents": int(ledger_net),
                "difference_cents": int(captured_net) - int(ledger_net),
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
