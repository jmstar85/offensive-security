"""PR-9 — feature flag double-enforcement (default OFF).

When ``OSA_KALI_BACKEND_ENABLED`` is False (the default), both
``get_adapter('kali_*')`` and ``palette_for_domain`` must hide the entire
kali surface from callers.
"""
from __future__ import annotations

import pytest

from app.agents.registry import (
    KaliBackendDisabledError,
    get_adapter,
    palette_for_domain,
)
from app.core.config import settings


@pytest.fixture(autouse=True)
def _force_kali_disabled(monkeypatch):
    monkeypatch.setattr(settings, "osa_kali_backend_enabled", False)


def test_default_flag_value_is_false():
    # Defensive: ensure the production default is False (the runbook gate).
    from app.core.config import Settings

    s = Settings()
    assert s.osa_kali_backend_enabled is False


@pytest.mark.parametrize("slug", ["kali_gobuster", "kali_sqlmap", "kali_nikto"])
def test_get_adapter_raises_when_disabled(slug):
    with pytest.raises(KaliBackendDisabledError) as exc:
        get_adapter(slug)
    assert slug in str(exc.value)


def test_get_adapter_legacy_unaffected_when_flag_off():
    # The legacy slugs are still reachable when the kali flag is off.
    adapter = get_adapter("nmap")
    assert adapter.agent_type == "nmap"


def test_palette_excludes_kali_when_disabled():
    palette = {e.slug for e in palette_for_domain(frozenset({"web", "api"}))}
    assert "kali_gobuster" not in palette
    assert "kali_sqlmap" not in palette
    assert "kali_nikto" not in palette
    # legacy web tools still surface
    assert "httpx" in palette
    assert "wappalyzer" in palette
