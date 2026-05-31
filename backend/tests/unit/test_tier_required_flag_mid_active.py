"""Unit tests for mid_active tier flag in TIER_REQUIRED_FLAG (PR3.7)."""
from __future__ import annotations

import pytest

from app.safety.exploit_allowlist import TIER_REQUIRED_FLAG, filter_by_tier_flags


# ── Map entry assertion ───────────────────────────────────────────────────────

def test_mid_active_in_tier_required_flag_map():
    assert TIER_REQUIRED_FLAG["mid_active"] == "approved_mid_active"


# ── Blocking behaviour ───────────────────────────────────────────────────────

def test_mid_active_step_without_flag_blocked():
    steps = [{"agent": "mitm_proxy", "tier": "mid_active", "config": {}}]
    approved, blocked = filter_by_tier_flags(steps, session_flags={})
    assert approved == []
    assert len(blocked) == 1
    assert "approved_mid_active" in blocked[0]["block_reason"]


def test_mid_active_step_with_flag_passes():
    steps = [{"agent": "mitm_proxy", "tier": "mid_active", "config": {}}]
    approved, blocked = filter_by_tier_flags(
        steps, session_flags={"approved_mid_active": True}
    )
    assert len(approved) == 1
    assert blocked == []


# ── Existing tiers unchanged ─────────────────────────────────────────────────

def test_existing_tier_flags_unchanged():
    assert TIER_REQUIRED_FLAG["active_recon"] == "approved_active_recon"
    assert TIER_REQUIRED_FLAG["active_exploit"] == "approved_active_exploit"


# ── Slug-level UI flags documentation test ───────────────────────────────────

def test_approved_mitm_proxy_alias_for_mid_active():
    # Slug-level flags (approved_mitm_proxy, approved_headless_browser,
    # approved_interactsh) are UI sugar rendered in ApprovalPreviewPanel.
    # The safety chain currently gates all mid_active tools under the single
    # 'approved_mid_active' tier flag.  The frontend aggregates any slug-level
    # toggle being True into approved_mid_active=True before posting to the API.
    # This test documents that contract: a step with tier=mid_active that has
    # approved_mid_active=True in session_flags is allowed.
    steps = [{"agent": "mitm_proxy", "tier": "mid_active", "config": {}}]
    approved, blocked = filter_by_tier_flags(
        steps, session_flags={"approved_mid_active": True}
    )
    assert len(approved) == 1
    assert blocked == []
