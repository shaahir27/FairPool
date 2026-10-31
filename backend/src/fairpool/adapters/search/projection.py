"""The one allowlisted public projection behind both search backends (T03B02).

Postgres is the source of truth, so the same SQL expression that the trigram
query scores is also the text the indexer writes to Elastic. One projection,
two backends: they cannot drift apart, and a private column (caps, buyer
requests, users, links, tokens, quote text) cannot reach an index by accident
(rule 23, FR-IG-01, ``docs/contracts/ai-schemas.md`` section 7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from sqlalchemy import ColumnElement, Select, column, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import Pool
from fairpool.db.models.enums import LotStatus, PoolStatus
from fairpool.db.models.pools import Lot

POOL_DOC: Final[str] = "pool"
LOT_DOC: Final[str] = "lot"

# The only fields a search backend may ever receive (ai-schemas.md section 7).
PUBLIC_FIELDS: Final[tuple[str, ...]] = (
    "doc_kind",
    "pool_id",
    "lot_id",
    "status",
    "product_key",
    "condition",
    "title",
    "content",
)

# A DRAFT pool is not public and a cancelled pool or lot has left the visible
# set, so it is neither searchable nor indexable (CR-3 "Sync details").
PUBLIC_POOL_STATUSES: Final[frozenset[str]] = frozenset(PoolStatus.__members__) - {
    PoolStatus.DRAFT.value,
    PoolStatus.CANCELLED.value,
}
PUBLIC_LOT_STATUSES: Final[frozenset[str]] = frozenset(LotStatus.__members__) - {
    LotStatus.CANCELLED.value
}

# The lots a merchant is still bidding on: the advisory check queries these
# (ai-schemas.md section 7 "Advisory wrong-product check").
OPEN_LOT_STATUSES: Final[tuple[str, ...]] = (LotStatus.BIDDING.value,)


def pool_content() -> ColumnElement[str]:
    """Pool document text: the derived ``search_text`` plus the delivery terms."""
    return func.concat_ws(
        " ",
        Pool.search_text,
        func.concat(
            "delivery ",
            func.coalesce(Pool.template["delivery_sla_days"].astext, ""),
            " days by ",
            func.coalesce(Pool.template["fund_by"].astext, ""),
        ),
    )


def lot_content() -> ColumnElement[str]:
    """Lot document text: the pool text plus the lot's own public zone and seat facts."""
    return func.concat_ws(
        " ",
        pool_content(),
        func.concat("zone ", Lot.zone_id),
        func.concat("seats ", Lot.seats),
        func.concat("min seats ", Lot.min_seats),
    )


@dataclass(frozen=True)
class PublicDocument:
    """One public pool or lot document, read from the committed row (CR-3)."""

    doc_kind: str
    pool_id: UUID
    lot_id: UUID | None
    status: str
    product_key: str
    condition: str
    title: str
    content: str

    @property
    def doc_id(self) -> UUID:
        """A document is keyed by the row id it describes (CR-3)."""
        return self.lot_id if self.doc_kind == LOT_DOC and self.lot_id else self.pool_id

    def fields(self) -> dict[str, Any]:
        """The only shape an index may receive; ids cross as strings."""
        return {
            "doc_kind": self.doc_kind,
            "pool_id": str(self.pool_id),
            "lot_id": str(self.lot_id) if self.lot_id is not None else None,
            "status": self.status,
            "product_key": self.product_key,
            "condition": self.condition,
            "title": self.title,
            "content": self.content,
        }


async def read_public_document(
    session: AsyncSession, *, doc_kind: str, doc_id: UUID
) -> PublicDocument | None:
    """Re-read the projection from the current committed row; ``None`` means not public."""
    if doc_kind == POOL_DOC:
        return await pool_document(session, doc_id)
    if doc_kind == LOT_DOC:
        return await lot_document(session, doc_id)
    raise ValueError(f"unknown search document kind: {doc_kind}")


async def pool_document(session: AsyncSession, pool_id: UUID) -> PublicDocument | None:
    row = (
        await session.execute(
            select(
                Pool.status,
                Pool.title,
                Pool.template["product_key"].astext,
                Pool.template["condition"].astext,
                pool_content(),
            ).where(Pool.id == pool_id)
        )
    ).first()
    if row is None:
        return None
    status, title, product_key, condition, content = row
    if str(status) not in PUBLIC_POOL_STATUSES:
        return None
    return PublicDocument(
        doc_kind=POOL_DOC,
        pool_id=pool_id,
        lot_id=None,
        status=str(status),
        product_key=product_key or "",
        condition=condition or "",
        title=title,
        content=content or "",
    )


async def lot_document(session: AsyncSession, lot_id: UUID) -> PublicDocument | None:
    row = (
        await session.execute(
            select(
                Lot.pool_id,
                Lot.status,
                Pool.status,
                Pool.title,
                Pool.template["product_key"].astext,
                Pool.template["condition"].astext,
                lot_content(),
            )
            .join(Pool, Pool.id == Lot.pool_id)
            .where(Lot.id == lot_id)
        )
    ).first()
    if row is None:
        return None
    pool_id, lot_status, pool_status, title, product_key, condition, content = row
    if str(pool_status) not in PUBLIC_POOL_STATUSES or str(lot_status) not in PUBLIC_LOT_STATUSES:
        return None
    return PublicDocument(
        doc_kind=LOT_DOC,
        pool_id=pool_id,
        lot_id=lot_id,
        status=str(lot_status),
        product_key=product_key or "",
        condition=condition or "",
        title=title,
        content=content or "",
    )


def public_documents_select() -> Select[Any]:
    """Every public document id, ordered for a paged reindex (admin-only route)."""
    pools = select(
        literal(POOL_DOC).label("doc_kind"),
        Pool.id.label("doc_id"),
    ).where(Pool.status.in_(sorted(PUBLIC_POOL_STATUSES)))
    lots = (
        select(literal(LOT_DOC).label("doc_kind"), Lot.id.label("doc_id"))
        .join(Pool, Pool.id == Lot.pool_id)
        .where(
            Lot.status.in_(sorted(PUBLIC_LOT_STATUSES)),
            Pool.status.in_(sorted(PUBLIC_POOL_STATUSES)),
        )
    )
    return pools.union_all(lots).order_by(column("doc_kind"), column("doc_id"))
