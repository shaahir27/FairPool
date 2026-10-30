"""Table-driven AI client fake.

Responses are keyed by the SHA-256 of the canonical task input. The contract
does not prescribe an exception type for an invalid model response or a timeout;
this fake raises typed built-in subclasses so callers can exercise both paths.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fairpool.domain import hashing
from fairpool.ports import AsyncSession, IntakeProposal, QuoteProposal, ReconcileResult

MODE_OK = "ok"
MODE_INVALID_JSON = "invalid_json"
MODE_TIMEOUT = "timeout"
_MODES = frozenset({MODE_OK, MODE_INVALID_JSON, MODE_TIMEOUT})

type FakeAIResponse = dict[str, Any] | str


class FakeAIInvalidJSON(ValueError):
    """The scripted model returned text that is not valid JSON."""


class FakeAITimeout(TimeoutError):
    """The scripted model call exceeded its deadline."""


@dataclass(frozen=True)
class FakeAICall:
    task: str
    input_hash: str
    payload: dict[str, Any]


class FakeAI:
    """Returns scripted responses keyed by task plus canonical input hash."""

    def __init__(
        self,
        *,
        mode: str = MODE_OK,
        responses: Mapping[str, FakeAIResponse] | None = None,
    ) -> None:
        if mode not in _MODES:
            raise ValueError(f"unknown FakeAI mode: {mode}")
        self.mode = mode
        self.responses: dict[str, FakeAIResponse] = dict(responses or {})
        self.calls: list[FakeAICall] = []

    @staticmethod
    def input_hash(task: str, payload: Mapping[str, Any]) -> str:
        return hashing.request_hash({"task": task, "input": dict(payload)})

    def register(
        self,
        task: str,
        payload: Mapping[str, Any],
        response: FakeAIResponse,
    ) -> str:
        digest = self.input_hash(task, payload)
        self.responses[digest] = response
        return digest

    def register_hash(self, input_hash: str, response: FakeAIResponse) -> None:
        self.responses[input_hash] = response

    def _prepare(self, task: str, payload: dict[str, Any]) -> FakeAIResponse:
        digest = self.input_hash(task, payload)
        self.calls.append(FakeAICall(task=task, input_hash=digest, payload=dict(payload)))
        if self.mode == MODE_INVALID_JSON:
            raise FakeAIInvalidJSON("scripted invalid JSON")
        if self.mode == MODE_TIMEOUT:
            raise FakeAITimeout("scripted timeout")
        try:
            return self.responses[digest]
        except KeyError:
            raise KeyError(f"no FakeAI response registered for {digest}") from None

    def _dict_response(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._prepare(task, payload)
        if not isinstance(response, dict):
            raise TypeError(f"{task} expects a dict response, got {type(response).__name__}")
        return response

    async def parse_intake(
        self,
        session: AsyncSession,
        *,
        message: str,
        candidates: list[dict[str, Any]],
        history: list[dict[str, Any]],
    ) -> IntakeProposal:
        payload = {"message": message, "candidates": candidates, "history": history}
        return self._dict_response("parse_intake", payload)

    async def parse_quote(
        self,
        session: AsyncSession,
        *,
        quote_text: str,
        lot_requirement: dict[str, Any],
    ) -> QuoteProposal:
        payload = {"quote_text": quote_text, "lot_requirement": lot_requirement}
        return self._dict_response("parse_quote", payload)

    async def reconcile_offer(
        self,
        session: AsyncSession,
        *,
        lot_requirement: dict[str, Any],
        bid_structured: dict[str, Any],
        text: str,
    ) -> ReconcileResult:
        payload = {
            "lot_requirement": lot_requirement,
            "bid_structured": bid_structured,
            "text": text,
        }
        return self._dict_response("reconcile_offer", payload)

    async def sim_text(
        self,
        session: AsyncSession,
        *,
        kind: str,
        facts: dict[str, Any],
    ) -> str:
        response = self._prepare("sim_text", {"kind": kind, "facts": facts})
        if not isinstance(response, str):
            raise TypeError(f"sim_text expects a str response, got {type(response).__name__}")
        return response
