"""Unit tests for agent adapters and the ExecutionBackend abstraction.

Tests:
  - NmapAdapter: command building, output parsing
  - NucleiAdapter: command building, output parsing
  - AgentAdapter base: execute() flow with mock backend
  - RiskLevel and capability assertions
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.agents.base import AgentResult, RiskLevel
from app.agents.nmap import NmapAdapter
from app.agents.nuclei import NucleiAdapter
from app.agents.metasploit import MetasploitAdapter
from app.agents.pyrit import PyRITAdapter


# ── NmapAdapter ───────────────────────────────────────────────────────────────

class TestNmapAdapter:
    def setup_method(self, method):
        self.backend = MagicMock()
        self.adapter = NmapAdapter(backend=self.backend)

    def test_agent_type(self):
        assert self.adapter.agent_type == "nmap"

    def test_risk_level_is_low(self):
        assert self.adapter.risk_level == RiskLevel.LOW

    def test_capabilities_include_port_scan(self):
        caps = self.adapter.get_capabilities()
        assert "port_scan" in caps

    def test_build_command_includes_target_ip(self):
        target = {"ip_ranges": ["192.168.1.0/24"], "domains": []}
        config = {"flags": "-sV -T4"}
        cmd = self.adapter.build_command(target, config)
        assert "192.168.1.0/24" in cmd
        assert "-sV" in " ".join(cmd)

    def test_build_command_includes_domain(self):
        target = {"ip_ranges": [], "domains": ["example.com"]}
        config = {}
        cmd = self.adapter.build_command(target, config)
        assert "example.com" in cmd

    def test_build_command_default_flags_are_sandbox_safe(self):
        # The default scan must not need CAP_NET_RAW (dropped in the hardened
        # agent container): TCP connect scan (-sT), skip host discovery (-Pn),
        # NO OS detection (-O) or default scripts (-sC) which require raw sockets
        # and otherwise fail with "failed to determine route".
        cmd = self.adapter.build_command({"ip_ranges": ["10.0.0.1"], "domains": []}, {})
        assert "-sT" in cmd
        assert "-Pn" in cmd
        assert "-O" not in cmd
        assert "-sC" not in cmd

    def test_build_command_drops_unresolvable_single_label_domain(self):
        # A single-label placeholder ("jarvis") is dropped when a real IP target
        # exists, so it does not flood the scan with "Failed to resolve".
        cmd = self.adapter.build_command(
            {"ip_ranges": ["20.196.207.37"], "domains": ["jarvis"]}, {}
        )
        assert "20.196.207.37" in cmd
        assert "jarvis" not in cmd

    def test_build_command_keeps_single_label_when_no_other_target(self):
        # If the ONLY targets are single-label (no IP/FQDN), keep them rather than
        # scanning nothing — nmap resolves or skips them as appropriate.
        cmd = self.adapter.build_command({"ip_ranges": [], "domains": ["jarvis"]}, {})
        assert "jarvis" in cmd

    def test_parse_output_empty_returns_empty_findings(self):
        result = self.adapter.parse_output("")
        assert isinstance(result, AgentResult)
        assert result.agent_type == "nmap"
        assert result.findings == []

    def test_parse_output_with_open_port(self):
        # Nmap XML-style output with open port
        raw = "80/tcp open http Apache httpd 2.4.41"
        result = self.adapter.parse_output(raw)
        assert result.success is True
        # Should find at least one port-related finding
        assert len(result.findings) >= 1

    def test_parse_output_no_hosts_still_succeeds(self):
        result = self.adapter.parse_output("Nmap scan report: 0 hosts up")
        assert result.success is True


# ── NucleiAdapter ─────────────────────────────────────────────────────────────

class TestNucleiAdapter:
    def setup_method(self, method):
        self.backend = MagicMock()
        self.adapter = NucleiAdapter(backend=self.backend)

    def test_agent_type(self):
        assert self.adapter.agent_type == "nuclei"

    def test_risk_level_is_medium(self):
        assert self.adapter.risk_level == RiskLevel.MEDIUM

    def test_capabilities_include_vuln_scan(self):
        caps = self.adapter.get_capabilities()
        assert any("scan" in c or "vuln" in c or "cve" in c for c in caps)

    def test_build_command_includes_target(self):
        target = {"ip_ranges": [], "domains": ["example.com"]}
        config = {}
        cmd = self.adapter.build_command(target, config)
        assert "example.com" in " ".join(cmd) or "example.com" in cmd

    def test_parse_output_empty_is_success_no_findings(self):
        result = self.adapter.parse_output("")
        assert result.success is True
        assert result.findings == []

    def test_parse_output_json_finding(self):
        finding_json = json.dumps({
            "template-id": "CVE-2021-44228",
            "info": {"name": "Log4Shell", "severity": "critical"},
            "matched-at": "http://example.com/api",
        })
        result = self.adapter.parse_output(finding_json)
        assert result.success is True
        assert len(result.findings) >= 1
        assert result.findings[0].get("severity") in ("critical", "high", "medium", "low", "info", None)


# ── MetasploitAdapter ─────────────────────────────────────────────────────────

class TestMetasploitAdapter:
    def setup_method(self, method):
        self.backend = MagicMock()
        self.adapter = MetasploitAdapter(backend=self.backend)

    def test_agent_type(self):
        assert self.adapter.agent_type == "metasploit"

    def test_risk_level_is_high(self):
        assert self.adapter.risk_level == RiskLevel.HIGH

    def test_capabilities_not_empty(self):
        assert len(self.adapter.get_capabilities()) > 0

    def test_build_command_not_empty(self):
        target = {"ip_ranges": ["192.168.1.1"], "domains": []}
        config = {"module": "auxiliary/scanner/portscan/tcp"}
        cmd = self.adapter.build_command(target, config)
        assert isinstance(cmd, list)
        assert len(cmd) > 0


# ── PyRITAdapter ──────────────────────────────────────────────────────────────

class TestPyRITAdapter:
    def setup_method(self, method):
        self.backend = MagicMock()
        self.adapter = PyRITAdapter(backend=self.backend)

    def test_agent_type(self):
        assert self.adapter.agent_type == "pyrit"

    def test_capabilities_not_empty(self):
        assert len(self.adapter.get_capabilities()) > 0

    def test_parse_output_empty_is_success(self):
        result = self.adapter.parse_output("")
        assert result.success is True


# ── AgentAdapter base execute() flow ─────────────────────────────────────────

class TestAgentAdapterExecuteFlow:
    @pytest.mark.asyncio
    async def test_execute_yields_log_events(self, mock_docker_backend):
        adapter = NmapAdapter(backend=mock_docker_backend)
        target = {"ip_ranges": ["192.168.1.1"], "domains": []}
        config = {}
        events = []
        async for evt in adapter.execute(target, config):
            events.append(evt)

        event_types = [e.event_type for e in events]
        assert "log" in event_types
        assert "status" in event_types

    @pytest.mark.asyncio
    async def test_execute_sets_execution_id_out(self, mock_docker_backend):
        adapter = NmapAdapter(backend=mock_docker_backend)
        exec_id_holder: list[str] = []
        async for _ in adapter.execute({"ip_ranges": ["10.0.0.1"], "domains": []}, {}, exec_id_holder):
            pass
        assert exec_id_holder == ["test-container-id"]

    @pytest.mark.asyncio
    async def test_execute_calls_cleanup(self, mock_docker_backend):
        adapter = NmapAdapter(backend=mock_docker_backend)
        async for _ in adapter.execute({"ip_ranges": ["10.0.0.1"], "domains": []}, {}):
            pass
        mock_docker_backend.cleanup.assert_called_once_with("test-container-id")


# ── Registry ──────────────────────────────────────────────────────────────────

class TestAgentRegistry:
    def test_get_known_agents(self):
        from unittest.mock import patch
        from app.agents.registry import get_adapter

        mock_backend = MagicMock()
        with patch("app.agents.registry.get_docker_backend", return_value=mock_backend):
            for agent_type in ["nmap", "nuclei", "metasploit", "pyrit"]:
                adapter = get_adapter(agent_type)
                assert adapter.agent_type == agent_type

    def test_unknown_agent_raises(self):
        from unittest.mock import patch
        from app.agents.registry import get_adapter
        mock_backend = MagicMock()
        with patch("app.agents.registry.get_docker_backend", return_value=mock_backend):
            with pytest.raises(ValueError, match="Unknown agent type"):
                get_adapter("unknown_tool")

    def test_list_agent_types(self):
        """Legacy agent slugs must still be registered (plan v3.2.1 extends, not replaces)."""
        from app.agents.registry import list_agent_types
        types = set(list_agent_types())
        assert {"nmap", "nuclei", "metasploit", "pyrit"} <= types
