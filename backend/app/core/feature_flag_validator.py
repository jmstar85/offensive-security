from __future__ import annotations

from typing import Any

_V1_FLAGS: tuple[str, ...] = (
    "osa_coordinator_enabled",
    "osa_multi_provider_llm",
    "osa_xbow_families_enabled",
    "osa_mitm_proxy_enabled",
    "osa_headless_browser_enabled",
    "osa_collaborator_enabled",
    "osa_traffic_via_mitm",
)

def _tuple_for(settings: Any) -> frozenset[tuple[str, bool]]:
    return frozenset(
        (flag, bool(getattr(settings, flag, False))) for flag in _V1_FLAGS
    )

def _all_false() -> frozenset[tuple[str, bool]]:
    return frozenset((flag, False) for flag in _V1_FLAGS)

def _only(*on_flags: str) -> frozenset[tuple[str, bool]]:
    return frozenset((flag, flag in on_flags) for flag in _V1_FLAGS)

# T1 — all 7 flags False (v1.1 parity)
_T1 = _all_false()
# T2 — multi-provider LLM only
_T2 = _only("osa_multi_provider_llm")
# T3 — multi-provider LLM + coordinator + xbow families
_T3 = _only("osa_multi_provider_llm", "osa_coordinator_enabled", "osa_xbow_families_enabled")
# T4 — all 7 True
_T4 = frozenset((flag, True) for flag in _V1_FLAGS)

_SUPPORTED: dict[str, frozenset[tuple[str, bool]]] = {
    "T1": _T1,
    "T2": _T2,
    "T3": _T3,
    "T4": _T4,
}


class UnsupportedFlagTopology(ValueError):
    pass


def _closest_tuple_name(candidate: frozenset[tuple[str, bool]]) -> str:
    best_name = "T1"
    best_score = -1
    for name, supported in _SUPPORTED.items():
        score = len(candidate & supported)
        if score > best_score:
            best_score = score
            best_name = name
    return best_name


def validate_flag_topology(settings: Any) -> None:
    """Raise UnsupportedFlagTopology in production when the active flag tuple is not T1..T4."""
    env = getattr(settings, "environment", "dev")
    if env != "production":
        return

    active = _tuple_for(settings)
    for name, supported in _SUPPORTED.items():
        if active == supported:
            return

    on_flags = sorted(flag for flag, val in active if val)
    closest = _closest_tuple_name(active)
    raise UnsupportedFlagTopology(
        f"Unsupported flag topology in production: {on_flags}. "
        f"Closest supported tuple is {closest}. "
        f"Supported tuples are T1..T4."
    )
