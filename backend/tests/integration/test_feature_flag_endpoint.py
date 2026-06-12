"""Feature-flag API tests (v4.0 P3-main)."""
from __future__ import annotations

import pytest


def test_feature_flag_module_exposes_endpoint():
    """`/api/v1/config/feature-flags` route is registered on the FastAPI app."""
    from app.main import app

    paths = [r.path for r in app.routes]
    assert "/api/v1/config/feature-flags" in paths


@pytest.mark.asyncio
async def test_feature_flag_endpoint_returns_current_flag_state(monkeypatch):
    """Calling the route returns a dict with the current osa_flow_ui_enabled state."""
    from app.api.v1 import feature_flags
    from app.core import config

    # Force flag ON for this test.
    monkeypatch.setattr(config.settings, "osa_flow_ui_enabled", True)
    monkeypatch.setattr(config.settings, "osa_kali_backend_enabled", False)
    response = await feature_flags.get_feature_flags()
    assert response["osa_flow_ui_enabled"] is True
    assert response["osa_kali_backend_enabled"] is False

    # And OFF.
    monkeypatch.setattr(config.settings, "osa_flow_ui_enabled", False)
    response = await feature_flags.get_feature_flags()
    assert response["osa_flow_ui_enabled"] is False
    assert response["osa_kali_backend_enabled"] is False


def test_feature_flag_default_posture():
    """PR10: the autonomous-lane enable flags default ON after the scanme E2E
    verified the full loop; the multi-provider credential vault stays OFF (the
    autonomous lane uses local Ollama via osa_llm_provider)."""
    from app.core.config import Settings

    fresh = Settings(_env_file=None)
    assert fresh.osa_flow_ui_enabled is True
    assert fresh.osa_coordinator_enabled is True
    assert fresh.osa_xbow_families_enabled is True
    assert fresh.osa_xbow_autonomous_enabled is True
    assert fresh.osa_kali_backend_enabled is True
    assert fresh.osa_multi_provider_llm is False
