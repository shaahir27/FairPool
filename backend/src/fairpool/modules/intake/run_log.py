"""AI attempt records participate in the caller's transaction."""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.enums import AiTask
from fairpool.db.models.platform import AiRun


class PostgresAiRunLogger:
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
        run_id = uuid4()
        session.add(
            AiRun(
                id=run_id,
                task=AiTask(task),
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
        await session.flush()
        return run_id
