"""Flag-tuple canary progression model — W5/PR5.4.

Deterministic cohort assignment based on session_id hash, allowing
gradual rollout from T1 → T2 → T3 → T4 (and reverse rollback) with
a single global "active percentage" knob per transition.
"""
from __future__ import annotations
import hashlib
import uuid
from typing import Literal

Tuple = Literal["T1", "T2", "T3", "T4"]

# Forward-only progression order; reverse is the inverse.
PROGRESSION_ORDER: list[Tuple] = ["T1", "T2", "T3", "T4"]


def cohort_percentage(session_id: uuid.UUID) -> int:
    """Return 0..99 cohort bucket for a session — deterministic.

    Uses the first 4 bytes of SHA-256 as a 32-bit int before % 100, so the
    modulo bias is ~1 part in 42 million (vs ~12% with a single byte) and
    cohorts are statistically uniform.
    """
    digest = hashlib.sha256(session_id.bytes).digest()
    return int.from_bytes(digest[:4], "big") % 100


def resolve_tuple_for_session(
    session_id: uuid.UUID,
    *,
    baseline_tuple: Tuple,
    target_tuple: Tuple,
    active_percentage: int,
) -> Tuple:
    """Return the tuple this session should run on.

    - If session's cohort < active_percentage → target_tuple
    - Else → baseline_tuple
    active_percentage must be in [0, 100]. 0 → all baseline, 100 → all target.
    """
    if active_percentage < 0 or active_percentage > 100:
        raise ValueError(f"active_percentage must be in [0,100], got {active_percentage}")
    if cohort_percentage(session_id) < active_percentage:
        return target_tuple
    return baseline_tuple


def adjacent_in_progression(a: Tuple, b: Tuple) -> bool:
    """True when (a, b) are adjacent in PROGRESSION_ORDER in either direction."""
    i, j = PROGRESSION_ORDER.index(a), PROGRESSION_ORDER.index(b)
    return abs(i - j) == 1


MAX_FLIP_SECONDS = 600  # 10 minute SLA per PR5.4
