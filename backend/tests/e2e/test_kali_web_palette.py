"""PR-9 — end-to-end happy-path through the Kali coexistence stack.

We exercise the full pipeline that a planner-generated kali_gobuster step
takes through the safety layers, the adapter, and the (mocked) KaliBackend:

    planner step → filter_plan_steps → KaliExecAdapter.build_command →
    WhitelistShim.verify → KaliBackend.start (mock) → stream_logs (mock) →
    KaliGobusterAdapter.parse_output → AgentResult with findings.

Fixture target: ``vulnerables/web-dvwa@sha256:`` + 64 zeros (placeholder
digest — the actual digest is pinned at staging time per the runbook).
The KaliBackend's docker client is replaced with a MagicMock that returns
deterministic gobuster output, so the test runs without a docker daemon.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agents.backends.kali import KaliBackend
from app.agents.kali_exec import KaliGobusterAdapter
from app.agents.registry import get_adapter, palette_for_domain
from app.core.config import settings
from app.safety.exploit_allowlist import filter_plan_steps

FIXTURE_TARGET_IMAGE = "vulnerables/web-dvwa@sha256:" + "0" * 64

GOBUSTER_OUTPUT = """\
===============================================================
Gobuster v3.6
===============================================================
/admin                (Status: 200) [Size: 1234]
/login.php            (Status: 302) [Size: 0]
/private              (Status: 403) [Size: 287]
"""


@pytest.fixture(autouse=True)
def _enable_kali(monkeypatch):
    monkeypatch.setattr(settings, "osa_kali_backend_enabled", True)


def test_kali_gobuster_in_web_palette():
    palette = {e.slug for e in palette_for_domain(frozenset({"web"}))}
    assert "kali_gobuster" in palette


def test_planner_step_passes_safety_layer():
    step = {
        "agent": "kali_gobuster",
        "tier": "active_recon",
        "config": {
            "tool_slug": "gobuster",
            "args": ["dir", "-u", "http://target/", "-w", "/wordlists/c.txt"],
        },
    }
    approved, blocked = filter_plan_steps([step])
    assert approved == [step]
    assert blocked == []


def test_get_adapter_kali_gobuster_routes_through_kali_backend():
    adapter = get_adapter("kali_gobuster")
    assert isinstance(adapter, KaliGobusterAdapter)
    assert isinstance(adapter.backend, KaliBackend)


def test_build_command_then_parse_full_loop():
    """The adapter composes the command via the shim and parses the result."""
    adapter = KaliGobusterAdapter(backend=KaliBackend())
    cmd = adapter.build_command(
        {"image": FIXTURE_TARGET_IMAGE},
        {
            "tool_slug": "gobuster",
            "args": ["dir", "-u", "http://target/", "-w", "/wordlists/c.txt"],
        },
    )
    assert cmd[:2] == ["/usr/bin/gobuster", "dir"]
    assert "/wordlists/c.txt" in cmd

    result = adapter.parse_output(GOBUSTER_OUTPUT)
    assert result.success
    paths = {f["path"] for f in result.findings}
    assert paths == {"/admin", "/login.php", "/private"}
    # severity, status, and size make it onto every finding.
    for finding in result.findings:
        assert finding["type"] == "directory_found"
        assert "status" in finding
        assert "size" in finding
        assert finding["severity"] == "info"


@pytest.mark.asyncio
async def test_kali_backend_start_invokes_docker_with_image():
    """KaliBackend.start hands the pinned fixture image to docker-py."""
    with patch("app.agents.backends.kali.docker.DockerClient") as dc:
        client = MagicMock(name="kali-client")
        client.containers.run.return_value = MagicMock(id="ctr-e2e-001")
        dc.return_value = client
        backend = KaliBackend()

    exec_id = await backend.start(
        image=FIXTURE_TARGET_IMAGE,
        command=["/usr/bin/gobuster", "dir", "-u", "http://target/",
                 "-w", "/wordlists/c.txt"],
        env={},
        network=None,
        resource_limits={},
    )
    assert exec_id == "ctr-e2e-001"
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["image"] == FIXTURE_TARGET_IMAGE
    # Hardening contract still applies.
    assert kwargs["read_only"] is True
    assert kwargs["cap_drop"] == ["ALL"]
