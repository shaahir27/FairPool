"""Seeded simulation pools (T08B04).

``modules.sim`` plans, allocates and stores a labelled SIMULATION pool. It imports
no PayPal adapter and makes no provider call (I12); the fake router is selected from
the pool mode by the auction lane at award time.
"""

from __future__ import annotations

from fairpool.modules.sim.generator import SimPlan, build_plan
from fairpool.modules.sim.handlers import SimRunHandler
from fairpool.modules.sim.run import SimResult, run_sim

__all__ = ["SimPlan", "SimResult", "SimRunHandler", "build_plan", "run_sim"]
