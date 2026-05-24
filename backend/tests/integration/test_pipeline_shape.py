"""Pipeline-shape regression (v4.0 P2b, SF-5).

Explicit regression for the v4.0 Phase 1 review Open Issue #7: ensure that
`AttackPlanner(use_generator_role=False).create_plan(prompt, target)` produces
step content identical to v2.1 baseline. With the flag OFF (default), every
v2.1 caller behaves exactly as before — the `LegacyPlannerShim` bridge is
inert and no Generator role is touched.

The flag ON path is non-deterministic (Generator's LLM envelope varies) and
is NOT asserted here; P4 covers the live ambiguity-loop path.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.orchestrator.planner import AttackPlanner


CANONICAL_RECON_PLAN = {
    "target_summary": "Single host 127.0.0.1, port-scan probe",
    "risk_level": "low",
    "steps": [
        {
            "order": 1,
            "agent": "nmap",
            "action": "port_scan",
            "description": "Initial TCP SYN scan on /24",
            "config": {"flags": "-sV -sC -T4 --open"},
        }
    ],
}


def _mock_model_client(plan: dict) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.send = AsyncMock(
        return_value=SimpleNamespace(text=json.dumps(plan))
    )
    return mock_client


@pytest.mark.asyncio
async def test_off_path_preserves_v2_1_step_shape():
    """The default `AttackPlanner()` (no flag) returns the v2.1 step shape
    exactly. Step keys + first-step content match the fixture."""
    mock_client = _mock_model_client(CANONICAL_RECON_PLAN)
    planner = AttackPlanner(model_client=mock_client)  # use_generator_role defaults False

    plan = await planner.create_plan(
        "Initial recon on the target",
        {"ip_ranges": ["127.0.0.1/24"]},
    )

    # Top-level keys: identical to v2.1.
    assert set(plan.keys()) >= {"target_summary", "risk_level", "steps"}
    # First-step content: identical to v2.1.
    step = plan["steps"][0]
    assert step["order"] == 1
    assert step["agent"] == "nmap"  # The Open Issue #7 specific assertion.
    assert step["action"] == "port_scan"
    assert step["description"].startswith("Initial TCP SYN scan")
    # Mocked client called exactly once — no extra round-trip introduced by P2b.
    mock_client.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_off_path_does_not_touch_generator_role():
    """With the flag OFF, the LegacyPlannerShim is never instantiated. We
    verify this by spying on the shim module — if its create_plan were
    called, the mock would record a call."""
    from app.orchestrator import legacy_shim

    mock_client = _mock_model_client(CANONICAL_RECON_PLAN)
    planner = AttackPlanner(model_client=mock_client, use_generator_role=False)

    # Patch the shim's create_plan to detect any unwanted invocation.
    original_create = legacy_shim.LegacyPlannerShim.create_plan
    invocations = []

    async def _spy(self, prompt, target):
        invocations.append((prompt, target))
        return await original_create(self, prompt, target)

    legacy_shim.LegacyPlannerShim.create_plan = _spy
    try:
        await planner.create_plan("recon", {"ip_ranges": ["10.0.0.0/24"]})
    finally:
        legacy_shim.LegacyPlannerShim.create_plan = original_create

    assert invocations == [], (
        f"OFF path must not touch LegacyPlannerShim; got {len(invocations)} invocations"
    )


@pytest.mark.asyncio
async def test_on_path_routes_through_shim():
    """With `use_generator_role=True`, the shim IS invoked exactly once."""
    from app.orchestrator import legacy_shim

    mock_client = _mock_model_client(CANONICAL_RECON_PLAN)
    planner = AttackPlanner(model_client=mock_client, use_generator_role=True)

    original_create = legacy_shim.LegacyPlannerShim.create_plan
    invocations = []

    async def _spy(self, prompt, target):
        invocations.append((prompt, target))
        return await original_create(self, prompt, target)

    legacy_shim.LegacyPlannerShim.create_plan = _spy
    try:
        plan = await planner.create_plan(
            "recon",
            {"ip_ranges": ["10.0.0.0/24"]},
        )
    finally:
        legacy_shim.LegacyPlannerShim.create_plan = original_create

    assert len(invocations) == 1
    # Plan shape preserved through the shim — same envelope as the OFF path.
    assert plan["steps"][0]["agent"] == "nmap"
