"""PR7 (C4) opt-in E2E: real Docker recon against scanme.nmap.org through the
autonomous safety-wired path.

Skipped by default. To run it you need: a reachable Docker daemon, the built
``osa-agent-nmap:latest`` image, outbound network to scanme.nmap.org, and:

    OSA_E2E_DOCKER_SCANME=1 PYTHONPATH=. .venv/bin/python -m pytest \
        tests/integration/test_scanme_real_docker_recon.py -v

The equivalent manual driver lives at ``scripts/verify_pr7_scanme.py``.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("OSA_E2E_DOCKER_SCANME") != "1",
    reason="opt-in: set OSA_E2E_DOCKER_SCANME=1 + Docker + osa-agent-nmap:latest image",
)

_TARGET = {"ip_ranges": [], "domains": ["scanme.nmap.org"]}
_WHITELIST = {"ip_ranges": ["45.33.32.156/32"], "domains": ["scanme.nmap.org"]}
_NMAP_CFG = {"network": "bridge", "flags": "-p 22,80,9929 -sV --open -T4 -Pn"}


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()

    async def _flush() -> None:
        pass

    db.flush = _flush
    db.execute = AsyncMock()
    return db


async def test_autonomous_dispatch_runs_real_nmap_against_scanme():
    """The autonomous _dispatch_tool path runs a real nmap container against scanme
    through the per-dispatch tier gate + shared runtime safety helper, and returns
    real open-port findings."""
    from app.orchestrator.performer import Performer

    perf = Performer(_mock_db(), uuid.uuid4())
    perf.bind_live_execution(
        target=_TARGET,
        approval_flags={"approved_active_recon": True},  # nmap = active_recon tier
        whitelist_rules=_WHITELIST,
        actor_id="e2e-scanme",
    )
    result = await perf._dispatch_tool("nmap", {"config": _NMAP_CFG})

    assert result["approved"] is True
    assert result.get("executed") is True
    assert result.get("killed") in (None, False)
    assert result.get("safety_violation") is None

    findings = result.get("findings") or []
    ports = {f.get("port") for f in findings if f.get("type") == "open_port"}
    # scanme.nmap.org reliably exposes 22 (ssh) and 80 (http).
    assert 22 in ports
    assert 80 in ports
