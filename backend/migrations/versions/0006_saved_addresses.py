"""Owner-requested encrypted profile prefill and reusable delivery addresses (CR-7)."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("paypal_signups", sa.Column("profile_enc", sa.LargeBinary(), nullable=True))
    op.create_table(
        "user_addresses",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("address_enc", sa.LargeBinary(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_user_addresses_user_id", "user_addresses", ["user_id"])
    op.create_index(
        "uq_user_addresses_default",
        "user_addresses",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.execute("ALTER TABLE user_addresses ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("user_addresses")
    op.drop_column("paypal_signups", "profile_enc")
