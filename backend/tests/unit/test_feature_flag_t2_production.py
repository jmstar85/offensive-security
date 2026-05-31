"""PR1.7 — verify T2 flag topology is accepted in production after W1 lands."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.feature_flag_validator import validate_flag_topology, UnsupportedFlagTopology

_ALL_FLAGS = (
    "osa_coordinator_enabled",
    "osa_multi_provider_llm",
    "osa_xbow_families_enabled",
    "osa_mitm_proxy_enabled",
    "osa_headless_browser_enabled",
    "osa_collaborator_enabled",
    "osa_traffic_via_mitm",
)


def _settings(**overrides: bool) -> SimpleNamespace:
    base = {flag: False for flag in _ALL_FLAGS}
    base["environment"] = "production"
    base.update(overrides)
    return SimpleNamespace(**base)


def test_t2_accepted_in_production() -> None:
    """T2 (osa_multi_provider_llm only) must be accepted without error in production."""
    cfg = _settings(osa_multi_provider_llm=True)
    result = validate_flag_topology(cfg)
    assert result is None


def test_t2_plus_coordinator_rejected_in_production() -> None:
    """T2 + osa_coordinator_enabled is not a supported tuple and must raise."""
    cfg = _settings(osa_multi_provider_llm=True, osa_coordinator_enabled=True)
    with pytest.raises(UnsupportedFlagTopology):
        validate_flag_topology(cfg)


def test_t2_plus_xbow_families_rejected_in_production() -> None:
    """T2 + osa_xbow_families_enabled alone is not T3 (missing coordinator) and must raise."""
    cfg = _settings(osa_multi_provider_llm=True, osa_xbow_families_enabled=True)
    with pytest.raises(UnsupportedFlagTopology):
        validate_flag_topology(cfg)
