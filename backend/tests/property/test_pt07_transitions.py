"""PT-07: every transition not in the YAML raises; listed ones are accepted.

Guards are contract text (no predicates in the domain), so this property covers
the whitelist itself: all (from, to) pairs of every machine, trigger selection
for pairs listed more than once, and the integrity of the transition table.
"""

from __future__ import annotations

import itertools
import string

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from fairpool.domain import states
from fairpool.domain.errors import IllegalTransition, UnknownMachine

pytestmark = pytest.mark.property

LISTED_PAIRS: dict[str, set[tuple[str, str]]] = {
    name: {
        (from_state, transition.to_state)
        for transition in machine.transitions
        for from_state in transition.from_states
    }
    for name, machine in states.MACHINES.items()
}

TRANSITIONS = tuple(states.TRANSITIONS_BY_ID.values())
MACHINE_NAMES = tuple(states.MACHINES)


def test_every_pair_of_states() -> None:
    """Enumerate all (from, to) pairs; only the whitelist may pass (I10)."""
    for name, machine in states.MACHINES.items():
        for from_state, to_state in itertools.product(machine.states, repeat=2):
            if (from_state, to_state) in LISTED_PAIRS[name]:
                transition = states.assert_transition(name, from_state, to_state)
                assert from_state in transition.from_states
                assert transition.to_state == to_state
                assert states.is_legal(name, from_state, to_state)
            else:
                with pytest.raises(IllegalTransition):
                    states.assert_transition(name, from_state, to_state)
                assert not states.is_legal(name, from_state, to_state)


@given(st.sampled_from(MACHINE_NAMES), st.text(max_size=20), st.text(max_size=20))
def test_random_state_pairs_follow_the_whitelist(
    machine_name: str, from_state: str, to_state: str
) -> None:
    if (from_state, to_state) in LISTED_PAIRS[machine_name]:
        assert states.is_legal(machine_name, from_state, to_state)
    else:
        assert not states.is_legal(machine_name, from_state, to_state)
        with pytest.raises(IllegalTransition):
            states.assert_transition(machine_name, from_state, to_state)


@given(st.sampled_from(TRANSITIONS), st.text(alphabet=string.ascii_letters + ":._", max_size=20))
def test_a_trigger_selects_only_listed_transitions(
    transition: states.Transition, trigger: str
) -> None:
    machine = states.MACHINES[transition.machine]
    triggers = {
        item.trigger
        for item in machine.transitions
        if item.to_state == transition.to_state and transition.from_states[0] in item.from_states
    }
    assume(trigger not in triggers)
    with pytest.raises(IllegalTransition):
        states.assert_transition(
            transition.machine,
            transition.from_states[0],
            transition.to_state,
            trigger=trigger,
        )


def test_transition_table_integrity() -> None:
    assert len(TRANSITIONS) == 64
    assert len({transition.id for transition in TRANSITIONS}) == 64
    for transition in TRANSITIONS:
        machine = states.MACHINES[transition.machine]
        assert transition in machine.transitions
        assert transition.from_states
        assert set(transition.from_states) <= set(machine.states)
        assert transition.to_state in machine.states
        assert transition.effects
        for effect in transition.effects:
            assert effect.startswith(("audit", "notify", "job:", "ledger:"))


def test_unknown_machines_are_rejected() -> None:
    with pytest.raises(UnknownMachine):
        states.assert_transition("refund", "OFFERED", "CAPTURED")
    with pytest.raises(UnknownMachine):
        states.is_legal("refund", "OFFERED", "CAPTURED")
