"""The MANDATE AI task (CR-14, FR-AI-06).

``ai_runs.task`` is the PostgreSQL enum ``ai_task``, created by ``0001`` with the four
values that existed then. A new task cannot be written until the type carries it, and
``AiTask("MANDATE")`` raises on the first insert otherwise.

Since PostgreSQL 12 an ``ALTER TYPE ... ADD VALUE`` may run inside a transaction; the one
restriction is that the new value cannot be *used* in the same transaction, and this
migration only adds it. ``tools/check_migrations.py`` replays 0001-to-head and so never
notices a missing value, which is why ``tests/integration/test_ai_task_enum.py`` writes a
real MANDATE row instead.
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE ai_task ADD VALUE IF NOT EXISTS 'MANDATE'")


def downgrade() -> None:
    # PostgreSQL cannot drop a single enum value, and rebuilding the type would rewrite
    # every ai_runs row. Removing the task is a data migration, not a schema step, so it
    # is refused rather than silently half-done.
    raise RuntimeError("ai_task cannot drop a value; restore the type explicitly if required")
