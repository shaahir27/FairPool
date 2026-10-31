"""Confirmed requests, save-attempt identity and lock-aware deadlines (CR-3).

Adds the durable records Phase 3 needs and repairs the deadline rule that let a
join waiting on a pool lock across ``close_at`` be admitted late. Migrations
0001 and 0002 are not rewritten.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_SETUP_STATUS = ("PENDING", "EXCHANGED", "FAILED", "QUARANTINED")

# I15, CR-3: the window is measured with clock_timestamp(), not now(). now() is
# fixed at transaction start, so a transaction that waits on the pool lock
# across close_at would still see the pre-close time and insert a late entry.
_FN_ENTRY_INSERT_WINDOW = """
CREATE OR REPLACE FUNCTION fn_entry_insert_window() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    pool_state pool_status;
    close_at_text text;
BEGIN
    SELECT status, timeline->>'close_at' INTO pool_state, close_at_text
    FROM pools WHERE id = NEW.pool_id;
    IF pool_state IS NULL THEN
        RAISE EXCEPTION 'unknown pool' USING ERRCODE = '23503';
    END IF;
    IF pool_state <> 'OPEN'::pool_status THEN
        RAISE EXCEPTION 'POOL_NOT_OPEN' USING ERRCODE = '23514';
    END IF;
    IF close_at_text IS NULL OR clock_timestamp() >= close_at_text::timestamptz THEN
        RAISE EXCEPTION 'POOL_CLOSED' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""

_FN_ENTRY_INSERT_WINDOW_BASE = """
CREATE OR REPLACE FUNCTION fn_entry_insert_window() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    pool_state pool_status;
    close_at_text text;
BEGIN
    SELECT status, timeline->>'close_at' INTO pool_state, close_at_text
    FROM pools WHERE id = NEW.pool_id;
    IF pool_state IS NULL THEN
        RAISE EXCEPTION 'unknown pool' USING ERRCODE = '23503';
    END IF;
    IF pool_state <> 'OPEN'::pool_status THEN
        RAISE EXCEPTION 'POOL_NOT_OPEN' USING ERRCODE = '23514';
    END IF;
    IF close_at_text IS NULL OR now() >= close_at_text::timestamptz THEN
        RAISE EXCEPTION 'POOL_CLOSED' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    literals = ", ".join(f"'{value}'" for value in _SETUP_STATUS)
    op.execute(f"CREATE TYPE vault_setup_status AS ENUM ({literals})")

    op.create_table(
        "confirmed_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("pool_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("rules_hash", sa.CHAR(64), nullable=False),
        sa.Column("canonical_request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_hash", sa.CHAR(64), nullable=False),
        sa.Column("cap_cents", sa.BigInteger(), nullable=False),
        sa.Column("zone_id", sa.Text(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_by_entry_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["consumed_by_entry_id"], ["pool_entries.id"], name=op.f("fk_confirmed_requests_entry")
        ),
        sa.ForeignKeyConstraint(["pool_id"], ["pools.id"], name=op.f("fk_confirmed_requests_pool")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_confirmed_requests_user")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_confirmed_requests")),
    )
    op.create_index("ix_confirmed_requests_pool_user", "confirmed_requests", ["pool_id", "user_id"])

    op.create_table(
        "vault_setup_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entry_id", sa.UUID(), nullable=False),
        sa.Column("operation_key", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*_SETUP_STATUS, name="vault_setup_status", create_type=False),
            server_default=sa.text("'PENDING'::vault_setup_status"),
            nullable=False,
        ),
        sa.Column("provider_setup_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("provider_setup_nonce", sa.LargeBinary(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["entry_id"], ["pool_entries.id"], name=op.f("fk_vault_setup_attempts_entry")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vault_setup_attempts")),
        sa.UniqueConstraint("operation_key", name="uq_vault_setup_attempts_operation_key"),
    )
    op.create_index(
        "ix_vault_setup_attempts_entry_status", "vault_setup_attempts", ["entry_id", "status"]
    )

    # The oauth_states table exists from 0001 but the login flow never ran, so it
    # is empty; binding it to the initiating session is only safe while it is.
    op.add_column("oauth_states", sa.Column("session_id", sa.UUID(), nullable=True))
    op.add_column(
        "oauth_states", sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        """DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM oauth_states WHERE session_id IS NULL) THEN
        RAISE EXCEPTION 'oauth_states holds rows with no initiating session; bind them first'
            USING ERRCODE = '23514';
    END IF;
    END $$"""
    )
    op.alter_column("oauth_states", "session_id", existing_type=sa.UUID(), nullable=False)
    op.create_foreign_key(
        "fk_oauth_states_session", "oauth_states", "sessions", ["session_id"], ["id"]
    )

    # vault_tokens.cap_cents was int, which caps a buyer at 2,147,483,647 cents
    # while pool_entries.cap_cents is already bigint.
    op.alter_column(
        "vault_tokens",
        "cap_cents",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )

    op.execute(_FN_ENTRY_INSERT_WINDOW)


def downgrade() -> None:
    op.execute(_FN_ENTRY_INSERT_WINDOW_BASE)
    op.alter_column(
        "vault_tokens",
        "cap_cents",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
    op.drop_constraint("fk_oauth_states_session", "oauth_states", type_="foreignkey")
    op.drop_column("oauth_states", "consumed_at")
    op.drop_column("oauth_states", "session_id")
    op.drop_index("ix_vault_setup_attempts_entry_status", table_name="vault_setup_attempts")
    op.drop_table("vault_setup_attempts")
    op.drop_index("ix_confirmed_requests_pool_user", table_name="confirmed_requests")
    op.drop_table("confirmed_requests")
    op.execute("DROP TYPE vault_setup_status")
