"""In-memory AI run logger fake."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid5

from fairpool.ports import AsyncSession

_NAMESPACE = UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")


@dataclass(frozen=True)
class AiRunRecord:
    task: str
    model: str
    prompt_version: str
    input_hash: str
    output: dict[str, Any] | None
    ok: bool
    error: str | None
    latency_ms: int
    tokens_in: int
    tokens_out: int


class FakeAiRunLogger:
    """Records AI runs and returns deterministic run IDs."""

    def __init__(self) -> None:
        self.calls: list[AiRunRecord] = []

    async def log(
        self,
        session: AsyncSession,
        *,
        task: str,
        model: str,
        prompt_version: str,
        input_hash: str,
        output: dict[str, Any] | None,
        ok: bool,
        error: str | None,
        latency_ms: int,
        tokens_in: int,
        tokens_out: int,
    ) -> UUID:
        self.calls.append(
            AiRunRecord(
                task=task,
                model=model,
                prompt_version=prompt_version,
                input_hash=input_hash,
                output=output,
                ok=ok,
                error=error,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        )
        return uuid5(_NAMESPACE, f"fairpool/ai-run/v1/{len(self.calls)}")
