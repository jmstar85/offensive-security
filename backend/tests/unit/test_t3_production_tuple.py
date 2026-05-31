"""Unit tests for T3 tuple acceptance/rejection in production — PR2b.5."""
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


def test_t3_tuple_accepted_in_production():
    settings = _make_settings(
        environment="production",
        osa_multi_provider_llm=True,
        osa_coordinator_enabled=True,
        osa_xbow_families_enabled=True,
    )
    assert validate_flag_topology(settings) is None


def test_t3_plus_extra_flag_rejected_in_production():
    settings = _make_settings(
        environment="production",
        osa_multi_provider_llm=True,
        osa_coordinator_enabled=True,
        osa_xbow_families_enabled=True,
        osa_mitm_proxy_enabled=True,
    )
    with pytest.raises(UnsupportedFlagTopology) as exc_info:
        validate_flag_topology(settings)
    msg = str(exc_info.value)
    assert any(label in msg for label in ("T3", "T4"))


def test_t3_minus_one_flag_rejected_in_production():
    # T3 without osa_xbow_families_enabled — not a valid tuple
    settings = _make_settings(
        environment="production",
        osa_multi_provider_llm=True,
        osa_coordinator_enabled=True,
        osa_xbow_families_enabled=False,
    )
    with pytest.raises(UnsupportedFlagTopology):
        validate_flag_topology(settings)


def test_t3_accepted_in_dev_env_regardless():
    # In dev any arbitrary subset must be allowed
    settings = _make_settings(
        environment="dev",
        osa_multi_provider_llm=True,
        osa_coordinator_enabled=True,
        osa_xbow_families_enabled=True,
        osa_mitm_proxy_enabled=True,
        osa_headless_browser_enabled=True,
    )
    assert validate_flag_topology(settings) is None


def test_t3_xbow_only_without_coordinator_rejected():
    # osa_xbow_families_enabled alone is not T3 and not any supported tuple
    settings = _make_settings(
        environment="production",
        osa_xbow_families_enabled=True,
    )
    with pytest.raises(UnsupportedFlagTopology):
        validate_flag_topology(settings)
