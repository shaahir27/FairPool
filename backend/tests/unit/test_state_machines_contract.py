"""Contract test: ``states.py`` equals the state-machines YAML and db enums.

The YAML blocks in ``docs/contracts/state-machines.md`` are the source of truth
(contract header). This test parses them with PyYAML and compares every state,
initial state, terminal/active list, transition field, job effect and ledger
effect. It also enumerates all (from, to) pairs and asserts that every pair not
listed raises ``IllegalTransition``.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from fairpool.domain import states
from fairpool.domain.errors import IllegalTransition, UnknownMachine

ROOT = Path(__file__).resolve().parents[3]
STATE_MACHINES_DOC = ROOT / "docs" / "contracts" / "state-machines.md"
DB_SCHEMA_DOC = ROOT / "docs" / "contracts" / "db-schema.md"
DOMAIN_PORTS_DOC = ROOT / "docs" / "contracts" / "domain-ports.md"

YAML_BLOCK = re.compile(r"```yaml\n(.*?)```", re.DOTALL)
ENUM_FOR_MACHINE = {
    "pool": "pool_status",
    "entry": "entry_status",
    "lot": "lot_status",
    "buyer_order": "buyer_order_status",
    "bid": "bid_status",
}
JOB_KIND = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*")
EXPECTED_TRANSITION_COUNT = 64
EFFECT_PREFIXES = ("audit", "notify", "job:", "ledger:")


def _yaml_machines() -> dict[str, dict[str, object]]:
    blocks = YAML_BLOCK.findall(STATE_MACHINES_DOC.read_text(encoding="utf-8"))
    assert len(blocks) == 5, "state-machines.md must contain five YAML blocks"
    parsed: dict[str, dict[str, object]] = {}
    for block in blocks:
        document = yaml.safe_load(block)
        assert isinstance(document, dict) and len(document) == 1
        name, definition = next(iter(document.items()))
        parsed[str(name)] = definition
    return parsed


def _table_rows(text: str) -> Iterator[list[str]]:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or set(stripped) <= set("|-: "):
            continue
        yield [cell.strip() for cell in stripped.strip("|").split("|")]


def _enum_values() -> dict[str, list[str]]:
    wanted = set(ENUM_FOR_MACHINE.values()) | {"ledger_kind"}
    values: dict[str, list[str]] = {}
    for cells in _table_rows(DB_SCHEMA_DOC.read_text(encoding="utf-8")):
        if len(cells) == 2 and cells[0] in wanted:
            values[cells[0]] = [item.strip() for item in cells[1].split(",")]
    missing = wanted - values.keys()
    assert not missing, f"enums missing from db-schema.md: {sorted(missing)}"
    return values


def _job_kinds() -> set[str]:
    kinds: set[str] = set()
    for cells in _table_rows(DOMAIN_PORTS_DOC.read_text(encoding="utf-8")):
        if len(cells) >= 2 and JOB_KIND.fullmatch(cells[0]) and cells[1] in {"A", "B"}:
            kinds.add(cells[0])
    assert kinds, "job kinds table not found in domain-ports.md"
    return kinds


YAML_MACHINES = _yaml_machines()
ENUM_VALUES = _enum_values()
JOB_KINDS = _job_kinds()
LEDGER_KINDS = set(ENUM_VALUES["ledger_kind"])


def test_yaml_blocks_cover_every_machine() -> None:
    """T00B01 acceptance: the state-machine tables are loaded from state-machines.md."""
    assert set(YAML_MACHINES) == set(states.MACHINES)


@pytest.mark.parametrize("machine_name", list(YAML_MACHINES))
def test_states_initial_and_terminal_match_yaml(machine_name: str) -> None:
    specification = YAML_MACHINES[machine_name]
    machine = states.MACHINES[machine_name]
    assert machine.name == machine_name
    assert list(machine.states) == specification["states"]
    assert machine.initial == specification["initial"]
    assert list(machine.terminal) == specification["terminal"]
    assert list(machine.active) == specification.get("active", [])
    assert machine.initial in machine.states
    assert set(machine.terminal) <= set(machine.states)
    assert set(machine.active) <= set(machine.states)


@pytest.mark.parametrize("machine_name", list(YAML_MACHINES))
def test_transitions_match_yaml(machine_name: str) -> None:
    specification = YAML_MACHINES[machine_name]
    expected = specification["transitions"]
    machine = states.MACHINES[machine_name]
    assert len(machine.transitions) == len(expected)
    for yaml_transition, transition in zip(expected, machine.transitions, strict=True):
        assert transition.id == yaml_transition["id"]
        assert list(transition.from_states) == yaml_transition["from"]
        assert transition.to_state == yaml_transition["to"]
        assert transition.trigger == yaml_transition["trigger"]
        assert transition.guard == yaml_transition["guard"]
        assert list(transition.effects) == yaml_transition.get("effects", [])
        assert transition.paypal == yaml_transition.get("paypal")
        assert transition.key == yaml_transition.get("key")
        assert transition.machine == machine_name
        assert set(transition.from_states) <= set(machine.states)
        assert transition.to_state in machine.states


@pytest.mark.parametrize(("machine_name", "enum_name"), sorted(ENUM_FOR_MACHINE.items()))
def test_states_equal_db_schema_enum(machine_name: str, enum_name: str) -> None:
    """T00B01 acceptance: state lists equal the db-schema.md enums."""
    assert list(states.MACHINES[machine_name].states) == ENUM_VALUES[enum_name]


def test_transition_ids_are_unique_and_indexed() -> None:
    assert len(states.TRANSITIONS_BY_ID) == EXPECTED_TRANSITION_COUNT
    for machine in states.MACHINES.values():
        ids = [transition.id for transition in machine.transitions]
        assert len(ids) == len(set(ids))
        for transition in machine.transitions:
            assert states.TRANSITIONS_BY_ID[transition.id] is transition
    yaml_count = sum(len(spec["transitions"]) for spec in YAML_MACHINES.values())
    assert yaml_count == EXPECTED_TRANSITION_COUNT


def test_job_and_ledger_effects_name_known_kinds() -> None:
    """T00B01 acceptance: job effects exist in domain-ports.md; ledger effects in ledger_kind."""
    for transition in states.TRANSITIONS_BY_ID.values():
        for effect in transition.effects:
            assert effect.startswith(EFFECT_PREFIXES), (transition.id, effect)
            if effect.startswith("job:"):
                assert effect.removeprefix("job:") in JOB_KINDS, (transition.id, effect)
            elif effect.startswith("ledger:"):
                assert effect.removeprefix("ledger:") in LEDGER_KINDS, (transition.id, effect)


@pytest.mark.parametrize("machine_name", list(states.MACHINES))
def test_every_unlisted_pair_raises(machine_name: str) -> None:
    """A test enumerates all (from, to) pairs and asserts unlisted ones raise."""
    machine = states.MACHINES[machine_name]
    listed = {
        (from_state, transition.to_state)
        for transition in machine.transitions
        for from_state in transition.from_states
    }
    for from_state, to_state in itertools.product(machine.states, repeat=2):
        if (from_state, to_state) in listed:
            transition = states.assert_transition(machine_name, from_state, to_state)
            assert from_state in transition.from_states
            assert transition.to_state == to_state
            assert states.is_legal(machine_name, from_state, to_state)
        else:
            with pytest.raises(IllegalTransition):
                states.assert_transition(machine_name, from_state, to_state)
            assert not states.is_legal(machine_name, from_state, to_state)


def test_trigger_selects_the_listed_transition() -> None:
    transition = states.assert_transition(
        "buyer_order", "CAPTURING", "CAPTURED", trigger="job:order.vault_charge"
    )
    assert transition.id == "BO-24"
    with pytest.raises(IllegalTransition):
        states.assert_transition("buyer_order", "CAPTURING", "CAPTURED", trigger="job:capture.poll")


def test_unknown_machine_raises() -> None:
    with pytest.raises(UnknownMachine):
        states.assert_transition("refund", "OFFERED", "CAPTURED")
    with pytest.raises(UnknownMachine):
        states.is_legal("nope", "OFFERED", "CAPTURED")
