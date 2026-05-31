"""Unit tests for feature_flag_validator — production-only topology enforcement."""
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


# --- production: supported tuples ---

def test_t1_all_off_accepted_in_production():
    settings = _make_settings(environment="production")
    assert validate_flag_topology(settings) is None


def test_t2_multi_llm_only_accepted_in_production():
    settings = _make_settings(environment="production", osa_multi_provider_llm=True)
    assert validate_flag_topology(settings) is None


def test_t3_three_flags_accepted_in_production():
    settings = _make_settings(
        environment="production",
        osa_multi_provider_llm=True,
        osa_coordinator_enabled=True,
        osa_xbow_families_enabled=True,
    )
    assert validate_flag_topology(settings) is None


def test_t4_all_on_accepted_in_production():
    settings = _make_settings(environment="production", **{flag: True for flag in _V1_FLAGS})
    assert validate_flag_topology(settings) is None


# --- production: unsupported tuple ---

def test_invalid_tuple_rejected_in_production():
    # Only coordinator=True (no multi_llm, no families) — not a supported tuple
    settings = _make_settings(environment="production", osa_coordinator_enabled=True)
    with pytest.raises(UnsupportedFlagTopology):
        validate_flag_topology(settings)


# --- non-production: no restriction ---

def test_non_production_allows_arbitrary_combinations():
    # Odd combo in dev — must not raise
    settings = _make_settings(
        environment="dev",
        osa_coordinator_enabled=True,
        osa_mitm_proxy_enabled=True,
    )
    result = validate_flag_topology(settings)
    assert result is None


# --- exception message mentions closest tuple name ---

def test_unsupported_flag_topology_message_lists_closest_tuple():
    settings = _make_settings(environment="production", osa_coordinator_enabled=True)
    with pytest.raises(UnsupportedFlagTopology) as exc_info:
        validate_flag_topology(settings)
    msg = str(exc_info.value)
    assert any(label in msg for label in ("T1", "T2", "T3", "T4"))
