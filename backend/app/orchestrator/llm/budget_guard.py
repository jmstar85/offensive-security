"""Two-layer pre-emptive session budget guard (PR1.5 / MF2).

Layer-A: called BEFORE asyncio.gather() spawns N parallel tasks.
         Estimates aggregate cost of all N tasks; raises if total would overshoot.
Layer-B: called INSIDE each gathered task BEFORE the LLM call fires.
         Checks whether this specific marginal cost would overshoot given current accum.

Both layers raise SessionBudgetExceeded — neither silently permits an overshoot.
"""
from __future__ import annotations

import math
import time
import uuid
from collections import deque
from typing import Deque, Tuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import PentestSession
from app.observability.metrics import metrics


class SessionBudgetExceeded(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# Per-provider EMA state: (ema_ratio, last_update_ts)
# Tracks rolling actual/estimated ratio with alpha=0.05
_provider_ema: dict[str, float] = {}
# Per-provider 24h sample deque: (timestamp, actual, estimate)
_provider_samples: dict[str, Deque[Tuple[float, float, float]]] = {}
_EMA_ALPHA = 0.05
_WINDOW_SECONDS = 86400.0  # 24 hours


def _update_estimator_ema(provider: str, actual: float, estimate: float) -> float:
    """Update EMA ratio for provider and return current ratio."""
    if estimate <= 0:
        return _provider_ema.get(provider, 1.0)

    ratio = actual / estimate
    current = _provider_ema.get(provider, ratio)
    new_ema = _EMA_ALPHA * ratio + (1.0 - _EMA_ALPHA) * current
    _provider_ema[provider] = new_ema

    now = time.time()
    if provider not in _provider_samples:
        _provider_samples[provider] = deque()
    _provider_samples[provider].append((now, actual, estimate))
    # Prune samples older than 24h
    while _provider_samples[provider] and now - _provider_samples[provider][0][0] > _WINDOW_SECONDS:
        _provider_samples[provider].popleft()

    return new_ema


class BudgetGuard:
    def __init__(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        hard_cap_usd: float,
    ) -> None:
        self._db = db
        self._session_id = session_id
        self._hard_cap_usd = hard_cap_usd

    async def _current_accum(self) -> float:
        result = await self._db.execute(
            select(PentestSession.cost_usd_accum).where(
                PentestSession.id == self._session_id
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return 0.0
        return float(row)

    async def layer_a_check(self, estimated_cost_usd: float) -> None:
        """Pre-spawn aggregate check. estimated_cost_usd = N * avg_cost_per_task."""
        accum = await self._current_accum()
        if accum + estimated_cost_usd > self._hard_cap_usd:
            metrics.budget_guard_layer_a_block_total.inc(reason="layer_a_aggregate")
            raise SessionBudgetExceeded("layer_a_aggregate")

    async def layer_b_check(self, actual_marginal_cost_usd: float) -> None:
        """Per-task pre-call check. Runs inside each gathered task before LLM call."""
        accum = await self._current_accum()
        if accum + actual_marginal_cost_usd > self._hard_cap_usd:
            metrics.budget_guard_layer_b_block_total.inc(reason="layer_b_marginal")
            raise SessionBudgetExceeded("layer_b_marginal")

    async def record(
        self,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        actual_cost_usd: float,
        pre_call_estimate: float = 0.0,
    ) -> None:
        """Increment Prometheus counters and bump session.cost_usd_accum atomically."""
        metrics.llm_tokens_total.inc(
            value=float(tokens_in),
            provider=provider,
            model=model,
            kind="prompt",
        )
        metrics.llm_tokens_total.inc(
            value=float(tokens_out),
            provider=provider,
            model=model,
            kind="completion",
        )
        metrics.llm_cost_usd_total.inc(
            value=actual_cost_usd,
            provider=provider,
            model=model,
        )

        await self._db.execute(
            update(PentestSession)
            .where(PentestSession.id == self._session_id)
            .values(
                cost_usd_accum=PentestSession.cost_usd_accum + actual_cost_usd
            )
        )

        if pre_call_estimate > 0:
            ema = _update_estimator_ema(provider, actual_cost_usd, pre_call_estimate)
            metrics.budget_guard_estimator_drift.set(value=ema, provider=provider)

    def semaphore_size_for_budget(
        self,
        headroom_usd: float,
        avg_cost_per_task: float,
    ) -> int:
        """Concurrency bound: floor(headroom / avg_cost) clamped to [1, 16]."""
        if avg_cost_per_task <= 0:
            return 1
        raw = math.floor(headroom_usd / avg_cost_per_task)
        return max(1, min(16, raw))
