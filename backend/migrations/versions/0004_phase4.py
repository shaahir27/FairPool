"""Phase 4 contract changes (CR-4).

Three additive changes, each required by a Phase 4 task and each stated in
`docs/contracts/db-schema.md`:

* a forced demo award has no bid behind it, so `awards.bid_revision_id` becomes nullable;
* `intake_proposals` holds the owner-bound, single-use proposal the confirm endpoint needs,
  because `ai_runs` has no owner and is a record of what the model did, not what the buyer saw;
* `lots.refill_waves` counts refill waves, which no column could hold before.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "awards",
        "bid_revision_id",
        existing_type=sa.UUID(),
        nullable=True,
    )

    op.add_column(
        "lots",
        sa.Column("refill_waves", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )

    op.create_table(
        "intake_proposals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("pool_id", sa.UUID(), nullable=False),
        sa.Column("proposal", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rules_hash", sa.CHAR(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["pool_id"], ["pools.id"], name=op.f("fk_intake_proposals_pool")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_intake_proposals_user")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intake_proposals")),
    )
    op.create_index("ix_intake_proposals_user_pool", "intake_proposals", ["user_id", "pool_id"])


def downgrade() -> None:
    op.drop_index("ix_intake_proposals_user_pool", table_name="intake_proposals")
    op.drop_table("intake_proposals")
    op.drop_column("lots", "refill_waves")
    op.alter_column(
        "awards",
        "bid_revision_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
