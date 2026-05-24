"""Fix #2 — /agents/catalog hides kali_* tools when OSA_KALI_BACKEND_ENABLED is off.

The orchestrator's get_adapter and palette_for_domain both gate on the
feature flag, but /agents/catalog and /agents/catalog/{agent_type} were
leaking kali_* into the UI even when the flag was off. This test pins the
flag-aware filtering at the API layer.
"""
from __future__ import annotations

import pytest

from app.api.v1.agents import _is_visible_tool
from app.agents.registry import get_tool_entry
from app.core.config import settings


def test_kali_slugs_hidden_when_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "osa_kali_backend_enabled", False)
    for slug in ("kali_gobuster", "kali_sqlmap", "kali_nikto"):
        entry = get_tool_entry(slug)
        assert entry is not None
        assert _is_visible_tool(entry) is False


def test_kali_slugs_visible_when_flag_on(monkeypatch):
    monkeypatch.setattr(settings, "osa_kali_backend_enabled", True)
    for slug in ("kali_gobuster", "kali_sqlmap", "kali_nikto"):
        entry = get_tool_entry(slug)
        assert _is_visible_tool(entry) is True


def test_legacy_slugs_always_visible(monkeypatch):
    monkeypatch.setattr(settings, "osa_kali_backend_enabled", False)
    for slug in ("nmap", "nuclei", "metasploit", "pyrit",
                 "passive_recon", "subfinder", "dnsx", "httpx",
                 "cloudenum", "wappalyzer"):
        entry = get_tool_entry(slug)
        assert entry is not None, f"missing legacy slug {slug}"
        assert _is_visible_tool(entry) is True


@pytest.mark.parametrize("flag_value", [True, False])
def test_filter_is_pure_function_of_flag(monkeypatch, flag_value):
    """The filter must not have hidden state beyond the settings flag."""
    monkeypatch.setattr(settings, "osa_kali_backend_enabled", flag_value)
    entry = get_tool_entry("kali_sqlmap")
    assert _is_visible_tool(entry) is flag_value
