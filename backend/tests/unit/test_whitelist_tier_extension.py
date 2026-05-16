"""Plan v3.2.1 §5.2 — WhitelistValidator tier extension (additive, strict)."""
from __future__ import annotations

import pytest

from app.safety.whitelist import WhitelistValidator


def test_legacy_validate_target_still_works():
    """Existing v3.1.x project-approval flow must not regress."""
    v = WhitelistValidator({"ip_ranges": ["10.0.0.0/24"], "domains": ["acme.com"]})
    ok, violations = v.validate_target({"ip_ranges": ["10.0.0.10"], "domains": ["www.acme.com"]})
    assert ok is True and violations == []


def test_validate_host_by_tier_active_recon_uses_active_allowed():
    v = WhitelistValidator({
        "passive_allowed": ["acme.com"],
        "active_allowed": ["beta.acme.com"],
    })
    ok, reason = v.validate_host_by_tier("beta.acme.com", "active_recon")
    assert ok is True and reason is None
    # acme.com is only in passive_allowed → rejected at active_recon
    ok2, reason2 = v.validate_host_by_tier("acme.com", "active_recon")
    assert ok2 is False and reason2 is not None


def test_validate_host_by_tier_passive_uses_passive_allowed():
    v = WhitelistValidator({
        "passive_allowed": ["acme.com"],
        "active_allowed": ["beta.acme.com"],
    })
    ok, _ = v.validate_host_by_tier("api.acme.com", "passive_low_touch")
    assert ok is True


def test_validate_host_by_tier_no_legacy_fallback():
    """Plan §5.2 strict: empty tier-specific list MUST reject."""
    v = WhitelistValidator({"ip_ranges": ["10.0.0.0/24"], "domains": ["acme.com"]})
    ok, reason = v.validate_host_by_tier("acme.com", "active_recon")
    assert ok is False
    assert "active_allowed" in reason


def test_wildcard_block_beats_every_allowlist():
    v = WhitelistValidator({
        "passive_allowed": ["acme.com"],
        "active_allowed": ["acme.com"],
        "exploit_allowed": ["acme.com"],
        "wildcard_block_regex": [r"^internal\..*"],
    })
    for tier in ("passive_no_target_contact", "passive_low_touch", "active_recon", "active_exploit"):
        ok, reason = v.validate_host_by_tier("internal.acme.com", tier)
        assert ok is False and "wildcard_block_regex" in reason


def test_validate_host_by_tier_subdomain_match():
    v = WhitelistValidator({"active_allowed": ["acme.com"]})
    ok, _ = v.validate_host_by_tier("api.acme.com", "active_recon")
    assert ok is True


def test_validate_host_by_tier_cidr_match():
    v = WhitelistValidator({"active_allowed": ["10.0.0.0/24"]})
    ok, _ = v.validate_host_by_tier("10.0.0.42", "active_recon")
    assert ok is True


def test_validate_host_by_tier_unknown_tier_rejected():
    v = WhitelistValidator({"active_allowed": ["acme.com"]})
    ok, reason = v.validate_host_by_tier("acme.com", "nuclear_recon")
    assert ok is False and "unknown tier" in reason


def test_is_wildcard_blocked_alone():
    v = WhitelistValidator({"wildcard_block_regex": [r".*\.gov$", r".*\.mil$"]})
    assert v.is_wildcard_blocked("agency.gov") is True
    assert v.is_wildcard_blocked("army.mil") is True
    assert v.is_wildcard_blocked("acme.com") is False


def test_exploit_allowed_required_for_exploit_tier():
    v = WhitelistValidator({
        "passive_allowed": ["acme.com"],
        "active_allowed": ["acme.com"],
        # exploit_allowed empty
    })
    ok, reason = v.validate_host_by_tier("acme.com", "active_exploit")
    assert ok is False
    assert "exploit_allowed" in reason


def test_classify_discovered_host_is_alias():
    v = WhitelistValidator({"active_allowed": ["acme.com"]})
    by_tier = v.validate_host_by_tier("acme.com", "active_recon")
    classify = v.classify_discovered_host("acme.com", "active_recon")
    assert by_tier == classify
