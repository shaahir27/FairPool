"""CR-10: a delegation scope that names nothing selects nothing.

``AgentService`` builds its pool conditions from the stored scope. An empty scope
meant "no filter", so a delegation row written past ``DelegationService.create``
reached every pool — the opposite of a scope (I11). The refusal is the contract's
``VALIDATION_ERROR`` and it happens where the conditions are built, before any read.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from fairpool.domain.errors import ApplicationError
from fairpool.modules.agentapi.service import _scope_conditions
from fairpool.modules.identity.delegations import AgentPrincipal


def principal(scope: dict[str, object]) -> AgentPrincipal:
    return AgentPrincipal(
        delegation_id=uuid4(),
        user_id=uuid4(),
        scope=scope,
        max_cap_cents=60000,
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
    )


def test_an_empty_scope_is_refused() -> None:
    with pytest.raises(ApplicationError) as refused:
        _scope_conditions(principal({}))
    assert refused.value.code == "VALIDATION_ERROR"


def test_a_scoped_delegation_still_builds_its_conditions() -> None:
    pool_id = uuid4()
    by_pool = _scope_conditions(principal({"pool_ids": [str(pool_id)]}))
    by_category = _scope_conditions(principal({"pool_ids": [], "category": "monitors"}))
    assert len(by_pool) == 1
    assert len(by_category) == 1


def test_the_explicit_unrestricted_form_is_still_allowed() -> None:
    """``DelegationService.create`` normalises "all pools" to an empty list, not {}."""
    assert _scope_conditions(principal({"pool_ids": [], "category": None})) == []
