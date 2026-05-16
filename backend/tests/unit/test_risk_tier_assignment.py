"""Plan v3.2.1 §2.4 — tier→risk mapping is exhaustive and registry-derived."""
import pytest

from app.safety.risk_filter import (
    TIER_RISK,
    base_risk_for_slug,
    tier_risk,
)
from app.agents.registry import list_tool_entries


def test_tier_risk_has_all_four_tiers():
    assert set(TIER_RISK.keys()) == {
        "passive_no_target_contact",
        "passive_low_touch",
        "active_recon",
        "active_exploit",
    }


def test_tier_risk_monotonic_increase():
    """Each higher tier must carry a strictly larger base weight."""
    assert (
        TIER_RISK["passive_no_target_contact"]
        < TIER_RISK["passive_low_touch"]
        < TIER_RISK["active_recon"]
        < TIER_RISK["active_exploit"]
    )


def test_every_registered_tool_has_known_tier():
    for entry in list_tool_entries():
        assert entry.tier in TIER_RISK, (entry.slug, entry.tier)


def test_base_risk_for_slug_uses_registry_tier():
    # subfinder is registered with tier=active_recon → 0.55
    assert base_risk_for_slug("subfinder") == TIER_RISK["active_recon"]
    # passive_recon → 0.05
    assert base_risk_for_slug("passive_recon") == TIER_RISK["passive_no_target_contact"]


def test_base_risk_for_unknown_slug_falls_back_to_legacy_default():
    assert base_risk_for_slug("definitely-not-registered") == 0.5


def test_tier_risk_raises_on_unknown_tier():
    with pytest.raises(ValueError):
        tier_risk("nuclear_recon")
