"""Agent connections and demand-formed pools (CR-17).

Two additions, both owner-requested:

* ``delegations`` gains the connection identity merchant keys already carry
  (``name``, ``key_prefix``, ``last_used_at``) plus the OAuth client that minted
  it, so the buyer sees connected agents rather than anonymous tokens.
  ``agent_oauth_clients`` and ``agent_oauth_codes`` carry the authorization-code
  flow; the access token itself stays a delegation, so there is one revocation
  path and one cap/scope enforcement path.
* ``demand_clusters`` and ``demand_signals`` record consented buyer interest in
  a product that has no pool yet. A signal stores the canonical product fields
  the buyer confirmed -- never a cap, a raw message or payment data -- and the
  cluster key is deterministic, so a similarity score never decides membership.

Existing delegation rows keep working: every new column is nullable, and an
unnamed row is still a valid token.
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_CLUSTER_STATES = "('COLLECTING','PROPOSED','POOLED','REJECTED','EXPIRED')"


def upgrade() -> None:
    op.create_table(
        "agent_oauth_clients",
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("redirect_uris", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column("delegations", sa.Column("name", sa.Text(), nullable=True))
    op.add_column("delegations", sa.Column("key_prefix", sa.Text(), nullable=True))
    op.add_column(
        "delegations", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "delegations",
        sa.Column(
            "oauth_client_id",
            sa.Text(),
            sa.ForeignKey("agent_oauth_clients.client_id"),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_delegations_key_prefix",
        "delegations",
        ["key_prefix"],
        unique=True,
        postgresql_where=sa.text("key_prefix IS NOT NULL"),
    )
    op.create_table(
        "agent_oauth_codes",
        sa.Column("code_hash", sa.Text(), primary_key=True),
        sa.Column(
            "client_id",
            sa.Text(),
            sa.ForeignKey("agent_oauth_clients.client_id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("scope", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("max_cap_cents", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "demand_clusters",
        sa.Column("cluster_key", sa.Text(), primary_key=True),
        sa.Column("product_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("features", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("regions", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            sa.CheckConstraint(f"status IN {_CLUSTER_STATES}", name="ck_demand_clusters_status"),
            nullable=False,
            server_default=sa.text("'COLLECTING'"),
        ),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("pool_id", sa.UUID(), sa.ForeignKey("pools.id"), nullable=True, unique=True),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pooled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "demand_signals",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "cluster_key",
            sa.Text(),
            sa.ForeignKey("demand_clusters.cluster_key"),
            nullable=False,
        ),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_demand_signals_cluster_key", "demand_signals", ["cluster_key"])
    op.create_index(
        "uq_demand_signals_user_cluster_active",
        "demand_signals",
        ["user_id", "cluster_key"],
        unique=True,
        postgresql_where=sa.text("cancelled_at IS NULL"),
    )
    op.execute("ALTER TABLE demand_signals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_oauth_codes ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("demand_signals")
    op.drop_table("demand_clusters")
    op.drop_table("agent_oauth_codes")
    op.drop_index("uq_delegations_key_prefix", table_name="delegations")
    op.drop_column("delegations", "oauth_client_id")
    op.drop_column("delegations", "last_used_at")
    op.drop_column("delegations", "key_prefix")
    op.drop_column("delegations", "name")
    op.drop_table("agent_oauth_clients")
