"""Plan v3.2.1 §4.3 — INTENT_VOCABULARY closed enum + domain mapping."""
import pytest

from app.agents.intent_vocabulary import (
    INTENT_VOCABULARY,
    intent_default_tier,
    intents_for_domain,
    is_valid_intent,
)


def test_vocabulary_has_at_least_20_items():
    assert len(INTENT_VOCABULARY) >= 20


def test_every_intent_has_known_tier():
    valid_tiers = {
        "passive_no_target_contact",
        "passive_low_touch",
        "active_recon",
        "active_exploit",
    }
    for slug, spec in INTENT_VOCABULARY.items():
        assert spec.default_tier in valid_tiers, (slug, spec.default_tier)


def test_every_intent_has_applicable_domains():
    for slug, spec in INTENT_VOCABULARY.items():
        assert spec.applicable_domain_tags, slug


def test_is_valid_intent_rejects_unknown():
    assert is_valid_intent("port_scan") is True
    assert is_valid_intent("hack_the_planet") is False


def test_intent_default_tier_known():
    assert intent_default_tier("port_scan") == "active_recon"
    assert intent_default_tier("breach_intel_lookup") == "passive_no_target_contact"


def test_intent_default_tier_unknown_raises():
    with pytest.raises(ValueError):
        intent_default_tier("not-an-intent")


def test_intents_for_web_domain_includes_recon_and_fingerprint():
    slugs = {s.slug for s in intents_for_domain(frozenset({"web"}))}
    assert "web_fingerprint" in slugs
    assert "vulnerability_template_scan" in slugs
    # secret_scan_public_repos applies to osint/cloud, not pure web
    assert "secret_scan_public_repos" not in slugs


def test_intents_for_cloud_aws_covers_credential_validation():
    slugs = {s.slug for s in intents_for_domain(frozenset({"cloud_aws"}))}
    assert "credential_validation" in slugs
    assert "cloud_bucket_enumeration" in slugs


def test_intents_for_ai_domain_includes_red_team_probe():
    slugs = {s.slug for s in intents_for_domain(frozenset({"ai"}))}
    assert "ai_red_team_probe" in slugs
