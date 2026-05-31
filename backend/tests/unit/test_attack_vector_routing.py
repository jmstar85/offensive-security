"""Tests for AttackVector enum, vector_to_tool_palette, and FamilySpawner."""
from __future__ import annotations

import pytest

from app.orchestrator.roles.registry import ROLE_REGISTRY
from app.orchestrator.roles.seed_xbow import (
    AttackVector,
    FamilySpawner,
    vector_to_tool_palette,
)
from app.agents.registry import list_agent_types


@pytest.fixture()
def clean_registry():
    """Snapshot ROLE_REGISTRY before test, restore it after."""
    snapshot = dict(ROLE_REGISTRY)
    yield
    ROLE_REGISTRY.clear()
    ROLE_REGISTRY.update(snapshot)


def test_attack_vector_enum_values():
    values = {v.value for v in AttackVector}
    assert values == {"web_app", "network", "cloud", "mobile", "unknown"}


def test_web_app_palette_only_web_slugs():
    legacy = set(list_agent_types())
    palette = vector_to_tool_palette[AttackVector.WEB_APP]
    assert all(slug in legacy for slug in palette), (
        f"web_app palette contains non-legacy slugs: {set(palette) - legacy}"
    )
    assert "nuclei" in palette
    assert "httpx" in palette
    assert "wappalyzer" in palette
    assert any(s.startswith("kali_") for s in palette)


def test_network_palette_only_network_slugs():
    legacy = set(list_agent_types())
    palette = vector_to_tool_palette[AttackVector.NETWORK]
    assert all(slug in legacy for slug in palette), (
        f"network palette contains non-legacy slugs: {set(palette) - legacy}"
    )
    assert "nmap" in palette
    assert "subfinder" in palette
    assert "dnsx" in palette


def test_cloud_palette_contains_cloudenum():
    palette = vector_to_tool_palette[AttackVector.CLOUD]
    assert "cloudenum" in palette


def test_palette_for_helper_returns_copy():
    spawner = FamilySpawner()
    result = spawner.palette_for(AttackVector.WEB_APP)
    result.append("__mutation__")
    assert "__mutation__" not in vector_to_tool_palette[AttackVector.WEB_APP]


def test_unknown_vector_falls_back_safely():
    palette = vector_to_tool_palette[AttackVector.UNKNOWN]
    assert len(palette) > 0, "UNKNOWN vector must have a non-empty fallback palette"


def test_no_palette_entry_outside_13_legacy_slugs():
    legacy = set(list_agent_types())
    for vector, palette in vector_to_tool_palette.items():
        for slug in palette:
            assert slug in legacy, (
                f"vector={vector.value} palette slug {slug!r} not in legacy 13-slug catalog"
            )


def test_family_spawner_rejects_above_hard_ceiling():
    with pytest.raises(ValueError, match="SF-CRITIC-6"):
        FamilySpawner(max_concurrent_per_family=9)
