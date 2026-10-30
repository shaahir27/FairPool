"""T01A01: the migration and models match db-schema.md exactly."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy.dialects.postgresql import CITEXT

from fairpool.db import migrations
from fairpool.db.base import Base
from fairpool.db.models import ENUM_TYPES, Pool, User
from fairpool.domain.states import MACHINES

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "docs/contracts/db-schema.md"
MIGRATION = ROOT / "backend/migrations/versions/0001_initial.py"

MACHINE_ENUMS = {
    "pool": "pool_status",
    "entry": "entry_status",
    "lot": "lot_status",
    "buyer_order": "buyer_order_status",
    "bid": "bid_status",
}


def contract_enums() -> dict[str, tuple[str, ...]]:
    text = SCHEMA.read_text(encoding="utf-8")
    section = text.split("## Enums", 1)[1].split("## Tables", 1)[0]
    enums: dict[str, tuple[str, ...]] = {}
    for line in section.splitlines():
        if not line.startswith("| ") or line.startswith("|---") or line.startswith("| Enum"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 2:
            continue
        enums[cells[0]] = tuple(value.strip() for value in cells[1].split(","))
    return enums


def test_all_contract_enums_exist_with_exact_values():
    expected = contract_enums()
    actual = {
        name: tuple(member.value for member in enum_cls) for name, enum_cls in ENUM_TYPES.items()
    }
    assert len(expected) == 21
    assert actual == expected


def test_state_machine_states_equal_the_five_ordering_enums():
    for machine_name, enum_name in MACHINE_ENUMS.items():
        values = tuple(member.value for member in ENUM_TYPES[enum_name])
        assert values == MACHINES[machine_name].states, machine_name


def test_all_32_tables_exist():
    contract = set(re.findall(r"^\*\*([a-z_]+)\*\*", SCHEMA.read_text(encoding="utf-8"), re.M))
    model_tables = set(Base.metadata.tables)
    assert len(contract) == 32
    assert model_tables == contract


def test_every_table_has_a_database_created_timestamp():
    for table in Base.metadata.tables.values():
        column = table.c.get("created_at")
        assert column is not None, f"{table.name} lacks created_at"
        assert column.nullable is False, table.name
        default = column.server_default
        assert default is not None, table.name
        assert "now()" in str(default.arg).lower(), table.name


def test_email_is_citext():
    assert isinstance(User.__table__.c.email.type, CITEXT)


def test_search_index_uses_gin_trigram_ops():
    index = next(i for i in Pool.__table__.indexes if i.name == "ix_pools_search_text_trgm")
    assert index.dialect_options["postgresql"]["using"] == "gin"
    assert index.dialect_options["postgresql"]["ops"] == {"search_text": "gin_trgm_ops"}


def test_circular_award_fk_is_deferred():
    foreign_keys = list(Base.metadata.tables["lots"].c.award_id.foreign_keys)
    assert len(foreign_keys) == 1
    assert foreign_keys[0].column.table.name == "awards"
    assert foreign_keys[0].constraint.use_alter is True


def test_migration_contains_extensions_triggers_and_named_check():
    text = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS citext" in text
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in text
    for trigger in (
        "trg_audit_append_only",
        "trg_ledger_append_only",
        "trg_awards_immutable",
        "trg_webhook_raw_immutable",
        "trg_pool_mode_immutable",
        "trg_entry_insert_window",
        "trg_entry_synthetic_matches_mode",
        "trg_paypal_rows_live_only",
        "trg_shipments_funded_only",
    ):
        assert f"CREATE TRIGGER {trigger}" in text
    assert "chk_usd_only" in text
    assert "idx_one_active_order_per_entry" in text
    assert "uq_vault_tokens_active_entry" in text


def test_head_revision_is_the_newest_migration():
    versions = sorted((ROOT / "backend/migrations/versions").glob("*.py"))
    assert versions, "no migrations"
    newest = versions[-1].stem.split("_", 1)[0]
    assert migrations.HEAD_REVISION == newest
