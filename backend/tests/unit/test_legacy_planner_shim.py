"""LegacyPlannerShim tests (v4.0 P2b).

Verifies the shim preserves the v2.1 plan envelope shape end-to-end. The
Claude API call is mocked so the test runs offline.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.orchestrator.legacy_shim import LegacyPlannerShim


@pytest.mark.asyncio
async def test_shim_preserves_v2_1_envelope_shape():
    """The shim returns a plan with `target_summary`, `risk_level`, `steps`."""
    mock_client = AsyncMock()
    mock_client.send.return_value = SimpleNamespace(
        text=json.dumps(
            {
                "target_summary": "Single host 127.0.0.1",
                "risk_level": "low",
                "steps": [
                    {
                        "order": 1,
                        "agent": "nmap",
                        "action": "port_scan",
                        "description": "Initial recon",
                        "config": {"flags": "-sV"},
                    }
                ],
            }
        )
    )

    shim = LegacyPlannerShim(model_client=mock_client)
    plan = await shim.create_plan("scan localhost", {"ip_ranges": ["127.0.0.1"]})

    assert set(plan.keys()) >= {"target_summary", "risk_level", "steps"}
    assert plan["risk_level"] == "low"
    assert plan["steps"][0]["agent"] == "nmap"


@pytest.mark.asyncio
async def test_shim_raises_on_malformed_plan():
    """If the underlying response is missing required keys, the shim raises
    rather than silently passing through. Protects callers from drift."""
    mock_client = AsyncMock()
    mock_client.send.return_value = SimpleNamespace(
        text=json.dumps({"only_irrelevant_key": "x"})
    )

    shim = LegacyPlannerShim(model_client=mock_client)
    with pytest.raises(ValueError, match="missing"):
        await shim.create_plan("test", {})


@pytest.mark.asyncio
async def test_shim_handles_codefenced_response():
    """Shim's underlying AttackPlanner strips ```json fences from the LLM
    response. Verify the shim inherits that behavior."""
    mock_client = AsyncMock()
    mock_client.send.return_value = SimpleNamespace(
        text=(
            "```json\n"
            + json.dumps(
                {
                    "target_summary": "host",
                    "risk_level": "medium",
                    "steps": [],
                }
            )
            + "\n```"
        )
    )

    shim = LegacyPlannerShim(model_client=mock_client)
    plan = await shim.create_plan("test", {})
    assert plan["risk_level"] == "medium"
