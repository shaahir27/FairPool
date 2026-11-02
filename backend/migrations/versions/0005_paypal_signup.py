"""Browser-bound PayPal-first registration (CR-6, owner request 2026-11-02)."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paypal_signups",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("state_hash", sa.CHAR(64), nullable=False, unique=True),
        sa.Column("browser_hash", sa.CHAR(64), nullable=False, unique=True),
        sa.Column("account_key", sa.CHAR(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "uq_paypal_signups_completed_account",
        "paypal_signups",
        ["account_key"],
        unique=True,
        postgresql_where=sa.text("completed_at IS NOT NULL"),
    )
    # Supabase exposes public tables through its Data API; only the backend owns this state.
    op.execute("ALTER TABLE paypal_signups ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("uq_paypal_signups_completed_account", table_name="paypal_signups")
    op.drop_table("paypal_signups")
