"""Property-based and exhaustive fuzz over all 128 flag topology combinations."""
import itertools
from types import SimpleNamespace

import pytest

from app.core.feature_flag_validator import (
    UnsupportedFlagTopology,
    _SUPPORTED,
    _V1_FLAGS,
    validate_flag_topology,
)

try:
    from hypothesis import given, settings as h_settings
    from hypothesis.strategies import booleans, tuples as h_tuples

    _HYPOTHESIS_AVAILABLE = True
except ImportError:
    _HYPOTHESIS_AVAILABLE = False


def _make_settings(environment: str, flag_values: tuple) -> SimpleNamespace:
    ns = SimpleNamespace(environment=environment)
    for flag, val in zip(_V1_FLAGS, flag_values):
        setattr(ns, flag, val)
    return ns


def _is_supported_combo(flag_values: tuple) -> bool:
    active = frozenset(zip(_V1_FLAGS, flag_values))
    return any(active == supported for supported in _SUPPORTED.values())


# --- hypothesis-based (skipped when hypothesis not installed) ---

if _HYPOTHESIS_AVAILABLE:
    @given(h_tuples(*[booleans()] * 7))
    @h_settings(max_examples=200)
    def test_hypothesis_dev_never_raises(flag_values):
        settings = _make_settings("dev", flag_values)
        validate_flag_topology(settings)  # must not raise


# --- always present: exhaustive 128-combo dev accepts all ---

def test_exhaustive_128_combos_dev_accepts_all():
    count = 0
    for flag_values in itertools.product((False, True), repeat=7):
        settings = _make_settings("dev", flag_values)
        assert validate_flag_topology(settings) is None, (
            f"dev mode unexpectedly raised for {flag_values}"
        )
        count += 1
    assert count == 128


# --- always present: exhaustive 128-combo prod rejects non-T1..T4 ---

def test_exhaustive_128_combos_prod_rejects_non_t1234():
    accepted = 0
    rejected = 0
    for flag_values in itertools.product((False, True), repeat=7):
        settings = _make_settings("production", flag_values)
        if _is_supported_combo(flag_values):
            assert validate_flag_topology(settings) is None, (
                f"production unexpectedly raised for supported combo {flag_values}"
            )
            accepted += 1
        else:
            with pytest.raises(UnsupportedFlagTopology):
                validate_flag_topology(settings)
            rejected += 1
    assert accepted == 4, f"Expected 4 accepted combos, got {accepted}"
    assert rejected == 124, f"Expected 124 rejected combos, got {rejected}"
