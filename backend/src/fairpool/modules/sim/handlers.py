"""``sim.run`` worker handler (T08B04; domain-ports.md section 5).

The handler owns the transaction that ``run_sim`` fills. It first executes the
measured path, then -- with the timer stopped -- may ask the model for wording on at
most twenty sample messages and stores those strings in ``sim_runs.results``. A model
outage never fails a simulation: the deterministic fallback text is stored instead,
labelled SIMULATED like every other simulation surface (FR-AI-03, FR-SM-01).
"""

from __future__ import annotations

import logging
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.platform import SimRun
from fairpool.domain.errors import ApplicationError
from fairpool.modules.sim.generator import SIM_SAMPLES
from fairpool.modules.sim.run import run_sim

logger = logging.getLogger("fairpool.sim")


class SimTextAI(Protocol):
    """The one model call this module may make, and never on the measured path."""

    async def sim_text(self, session: AsyncSession, *, kind: str, facts: dict[str, Any]) -> str: ...


class SimRunHandler:
    """Register as ``"sim.run": SimRunHandler(...).run`` in ``worker_handlers``."""

    def __init__(self, ai: SimTextAI | None = None) -> None:
        self.ai = ai

    async def run(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        sim_run_id = UUID(str(payload["sim_run_id"]))
        row = await session.get(SimRun, sim_run_id, with_for_update=True)
        if row is None:
            raise ApplicationError("NOT_FOUND")
        if row.results is not None:
            # The measured result is already stored; a retry writes nothing (I15).
            return
        result = await run_sim(session, dict(row.config), pool_id=row.pool_id)
        samples: list[dict[str, Any]] = []
        ai = self.ai
        used_model = False
        for message in result.samples[:SIM_SAMPLES]:
            text = message.text
            if ai is not None:
                try:
                    text = await ai.sim_text(session, kind=message.kind, facts=message.facts)
                    used_model = True
                except Exception as exc:
                    # Text variety is decoration; the measured run already succeeded.
                    # Only the exception type is logged: provider bodies may carry
                    # request data (I14).
                    logger.warning(
                        "sim.text_unavailable sim_run_id=%s kind=%s error=%s",
                        sim_run_id,
                        message.kind,
                        type(exc).__name__,
                    )
                    ai = None
            samples.append(
                {
                    "kind": message.kind,
                    "facts": message.facts,
                    "text": text,
                    "label": "SIMULATED",
                }
            )
        row.results = {
            **result.as_dict(),
            "samples": samples,
            "model_text": used_model,
        }
        await session.flush()


__all__ = ["SimRunHandler", "SimTextAI"]
