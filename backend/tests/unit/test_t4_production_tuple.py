"""Unit tests for T4 tuple acceptance/rejection in production — PR3.9."""
import pytest
from types import SimpleNamespace

from app.core.feature_flag_validator import (
    UnsupportedFlagTopology,
    validate_flag_topology,
    _V1_FLAGS,
)


def _make_settings(environment: str = "production", **flags) -> SimpleNamespace:
    ns = SimpleNamespace(environment=environment)
    for flag in _V1_FLAGS:
        setattr(ns, flag, flags.get(flag, False))
    return ns


def test_t4_tuple_accepted_in_production():
    settings = _make_settings(
        environment="production",
        osa_coordinator_enabled=True,
        osa_multi_provider_llm=True,
        osa_xbow_families_enabled=True,
        osa_mitm_proxy_enabled=True,
        osa_headless_browser_enabled=True,
        osa_collaborator_enabled=True,
        osa_traffic_via_mitm=True,
    )
    assert validate_flag_topology(settings) is None


def test_t4_minus_one_flag_rejected():
    # T4 minus osa_traffic_via_mitm — not a valid tuple
    settings = _make_settings(
        environment="production",
        osa_coordinator_enabled=True,
        osa_multi_provider_llm=True,
        osa_xbow_families_enabled=True,
        osa_mitm_proxy_enabled=True,
        osa_headless_browser_enabled=True,
        osa_collaborator_enabled=True,
        osa_traffic_via_mitm=False,
    )
    with pytest.raises(UnsupportedFlagTopology) as exc_info:
        validate_flag_topology(settings)
    msg = str(exc_info.value)
    assert any(label in msg for label in ("T4", "T3"))


def test_t4_in_dev_passes_unchanged():
    settings = _make_settings(
        environment="dev",
        osa_coordinator_enabled=True,
        osa_multi_provider_llm=True,
        osa_xbow_families_enabled=True,
        osa_mitm_proxy_enabled=True,
        osa_headless_browser_enabled=True,
        osa_collaborator_enabled=True,
        osa_traffic_via_mitm=True,
    )
    assert validate_flag_topology(settings) is None


def test_t4_when_environment_unset_passes():
    # environment defaults to 'dev' when not set — validator skips production check
    ns = SimpleNamespace()
    for flag in _V1_FLAGS:
        setattr(ns, flag, True)
    # no environment attribute set — getattr defaults to 'dev'
    assert validate_flag_topology(ns) is None
