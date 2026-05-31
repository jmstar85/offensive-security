"""Unit tests for W3 ToolEntry additions to the agent registry (PR3.6)."""
from __future__ import annotations

import pytest

from app.agents.registry import list_agent_types, list_tool_entries, get_tool_entry


# ── Individual slug tier assertions ──────────────────────────────────────────

def test_mitm_proxy_registered_with_mid_active_tier():
    entry = get_tool_entry("mitm_proxy")
    assert entry is not None
    assert entry.tier == "mid_active"


def test_headless_browser_registered_with_mid_active_tier():
    entry = get_tool_entry("headless_browser")
    assert entry is not None
    assert entry.tier == "mid_active"


def test_session_manager_registered_with_mid_active_tier():
    entry = get_tool_entry("session_manager")
    assert entry is not None
    assert entry.tier == "mid_active"


def test_interactsh_collaborator_registered_passive_low_touch():
    entry = get_tool_entry("interactsh_collaborator")
    assert entry is not None
    assert entry.tier == "passive_low_touch"


def test_kali_xsstrike_registered_active_exploit():
    entry = get_tool_entry("kali_xsstrike")
    assert entry is not None
    assert entry.tier == "active_exploit"


def test_kali_dalfox_registered_active_exploit():
    entry = get_tool_entry("kali_dalfox")
    assert entry is not None
    assert entry.tier == "active_exploit"


def test_kali_ffuf_registered_active_recon():
    entry = get_tool_entry("kali_ffuf")
    assert entry is not None
    assert entry.tier == "active_recon"


def test_kali_commix_registered_active_exploit():
    entry = get_tool_entry("kali_commix")
    assert entry is not None
    assert entry.tier == "active_exploit"


# ── Count assertion: 13 legacy + 8 W3 = 21 ──────────────────────────────────

def test_total_slug_count_is_21():
    slugs = list_agent_types()
    assert len(slugs) == 21, f"Expected 21 slugs, got {len(slugs)}: {slugs}"


# ── All mid_active entries have non-empty descriptions ───────────────────────

def test_mid_active_slugs_all_have_descriptions():
    mid_active_entries = [e for e in list_tool_entries() if e.tier == "mid_active"]
    assert mid_active_entries, "No mid_active entries found"
    for entry in mid_active_entries:
        assert entry.description, f"mid_active entry '{entry.slug}' has empty description"
