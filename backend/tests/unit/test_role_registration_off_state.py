"""Tests proving ROLE_REGISTRY is pristine of xbow slugs when flag is off."""
from __future__ import annotations

import pytest

from app.orchestrator.roles.registry import (
    ROLE_REGISTRY,
    lazy_register_if_enabled,
    list_roles,
)

_XBOW_SLUGS = {"session_management_agent", "discovery_agent", "attack_agent"}


@pytest.fixture()
def clean_registry():
    """Snapshot ROLE_REGISTRY before test, restore it after."""
    snapshot = dict(ROLE_REGISTRY)
    yield
    ROLE_REGISTRY.clear()
    ROLE_REGISTRY.update(snapshot)


def test_registry_empty_of_xbow_roles_when_flag_off(clean_registry):
    lazy_register_if_enabled(False)
    registered = set(list_roles())
    assert _XBOW_SLUGS.isdisjoint(registered), (
        f"xbow slugs leaked into registry: {_XBOW_SLUGS & registered}"
    )


def test_seed_minimal6_unchanged(clean_registry):
    import app.orchestrator.roles.seed  # noqa: F401 — trigger minimal-6 registration
    registered = set(list_roles())
    assert _XBOW_SLUGS.isdisjoint(registered), (
        f"seed.py import caused xbow slug registration: {_XBOW_SLUGS & registered}"
    )


def test_lazy_register_returns_false_when_flag_off(clean_registry):
    result = lazy_register_if_enabled(False)
    assert result is False


def test_lazy_register_with_flag_on_registers_three(clean_registry):
    result = lazy_register_if_enabled(True)
    assert result is True
    registered = set(list_roles())
    assert _XBOW_SLUGS.issubset(registered), (
        f"expected xbow slugs after flag=True: missing {_XBOW_SLUGS - registered}"
    )
