"""Unit tests for all safety guard components.

Tests:
  - WhitelistValidator: IP/CIDR/domain scope enforcement
  - RiskFilter: step risk assessment and filtering
  - ExploitAllowlist: MSF module and Nuclei tag gating
  - KillSwitch: session termination (with mock DB)
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import RiskLevel
from app.safety.exploit_allowlist import (
    filter_plan_steps,
    is_msf_module_approved,
    is_nuclei_tag_blocked,
)
from app.safety.risk_filter import RiskFilter
from app.safety.whitelist import WhitelistValidator


# ── WhitelistValidator ────────────────────────────────────────────────────────

class TestWhitelistValidator:
    def test_ip_in_allowed_cidr_passes(self):
        v = WhitelistValidator({"ip_ranges": ["192.168.1.0/24"], "domains": []})
        assert v.validate_ip("192.168.1.100") is True

    def test_ip_outside_cidr_fails(self):
        v = WhitelistValidator({"ip_ranges": ["192.168.1.0/24"], "domains": []})
        assert v.validate_ip("10.0.0.1") is False

    def test_exact_domain_passes(self):
        v = WhitelistValidator({"ip_ranges": [], "domains": ["example.com"]})
        assert v.validate_domain("example.com") is True

    def test_subdomain_passes(self):
        v = WhitelistValidator({"ip_ranges": [], "domains": ["example.com"]})
        assert v.validate_domain("api.example.com") is True

    def test_unrelated_domain_fails(self):
        v = WhitelistValidator({"ip_ranges": [], "domains": ["example.com"]})
        assert v.validate_domain("evil.com") is False

    def test_validate_target_all_in_scope_passes(self):
        v = WhitelistValidator({
            "ip_ranges": ["192.168.1.0/24"],
            "domains": ["example.com"],
        })
        ok, violations = v.validate_target({
            "ip_ranges": ["192.168.1.50"],
            "domains": ["api.example.com"],
        })
        assert ok is True
        assert violations == []

    def test_validate_target_out_of_scope_ip_fails(self):
        v = WhitelistValidator({"ip_ranges": ["192.168.1.0/24"], "domains": []})
        ok, violations = v.validate_target({"ip_ranges": ["10.0.0.1"], "domains": []})
        assert ok is False
        assert len(violations) == 1
        assert "out of scope" in violations[0]

    def test_validate_target_out_of_scope_domain_fails(self):
        v = WhitelistValidator({"ip_ranges": [], "domains": ["example.com"]})
        ok, violations = v.validate_target({"ip_ranges": [], "domains": ["evil.com"]})
        assert ok is False
        assert "Domain out of scope" in violations[0]

    def test_empty_whitelist_blocks_everything(self):
        v = WhitelistValidator({"ip_ranges": [], "domains": []})
        assert v.validate_ip("192.168.1.1") is False
        assert v.validate_domain("example.com") is False

    def test_invalid_ip_fails_gracefully(self):
        v = WhitelistValidator({"ip_ranges": ["192.168.1.0/24"], "domains": []})
        assert v.validate_ip("not-an-ip") is False

    def test_multiple_networks(self):
        v = WhitelistValidator({
            "ip_ranges": ["192.168.1.0/24", "10.0.0.0/8"],
            "domains": [],
        })
        assert v.validate_ip("192.168.1.50") is True
        assert v.validate_ip("10.5.6.7") is True
        assert v.validate_ip("172.16.0.1") is False


# ── RiskFilter ────────────────────────────────────────────────────────────────

class TestRiskFilter:
    def setup_method(self):
        self.rf = RiskFilter()

    def test_nmap_step_is_low_risk(self):
        step = {"agent": "nmap", "action": "port_scan"}
        assert self.rf.assess_step(step) == RiskLevel.LOW

    def test_nuclei_step_is_medium_risk(self):
        step = {"agent": "nuclei", "action": "vuln_scan"}
        assert self.rf.assess_step(step) == RiskLevel.MEDIUM

    def test_metasploit_step_is_high_risk(self):
        step = {"agent": "metasploit", "action": "exploit"}
        assert self.rf.assess_step(step) == RiskLevel.HIGH

    def test_dos_action_is_critical(self):
        step = {"agent": "nmap", "action": "dos_flood"}
        assert self.rf.assess_step(step) == RiskLevel.CRITICAL

    def test_ransomware_action_is_critical(self):
        step = {"agent": "metasploit", "action": "deploy_ransomware"}
        assert self.rf.assess_step(step) == RiskLevel.CRITICAL

    def test_filter_steps_blocks_critical(self):
        steps = [
            {"agent": "nmap", "action": "port_scan"},
            {"agent": "nmap", "action": "dos_attack"},
        ]
        allowed, blocked = self.rf.filter_steps(steps)
        assert len(allowed) == 1
        assert len(blocked) == 1
        assert blocked[0]["action"] == "dos_attack"

    def test_filter_steps_allows_non_critical(self):
        steps = [
            {"agent": "nmap", "action": "port_scan"},
            {"agent": "nuclei", "action": "vuln_scan"},
            {"agent": "metasploit", "action": "auxiliary_scan"},
        ]
        allowed, blocked = self.rf.filter_steps(steps)
        assert len(allowed) == 3
        assert len(blocked) == 0

    def test_score_plan_empty_returns_zero(self):
        assert self.rf.score_plan([]) == 0.0

    def test_score_plan_nmap_only_is_low(self):
        steps = [{"agent": "nmap", "action": "scan"}]
        score = self.rf.score_plan(steps)
        assert score == 1.0  # 0.1 * 10

    def test_score_plan_metasploit_is_high(self):
        steps = [{"agent": "metasploit", "action": "exploit"}]
        score = self.rf.score_plan(steps)
        assert score == 8.0  # 0.8 * 10


# ── ExploitAllowlist ──────────────────────────────────────────────────────────

class TestExploitAllowlist:
    def test_approved_msf_auxiliary_scanner_passes(self):
        assert is_msf_module_approved("auxiliary/scanner/portscan/tcp") is True

    def test_approved_msf_post_gather_passes(self):
        assert is_msf_module_approved("post/multi/gather/env") is True

    def test_unapproved_msf_exploit_fails(self):
        assert is_msf_module_approved("exploit/windows/smb/ms17_010_eternalblue") is False

    def test_unapproved_msf_empty_fails(self):
        assert is_msf_module_approved("") is False

    def test_nuclei_dos_tag_is_blocked(self):
        assert is_nuclei_tag_blocked(["dos", "network"]) is True

    def test_nuclei_fuzz_tag_is_blocked(self):
        assert is_nuclei_tag_blocked(["fuzz"]) is True

    def test_nuclei_safe_tags_pass(self):
        assert is_nuclei_tag_blocked(["cve", "rce", "sqli"]) is False

    def test_filter_plan_steps_metasploit_approved_module(self):
        steps = [{"agent": "metasploit", "config": {"module": "auxiliary/scanner/portscan/tcp"}}]
        approved, blocked = filter_plan_steps(steps)
        assert len(approved) == 1
        assert len(blocked) == 0

    def test_filter_plan_steps_metasploit_unapproved_module(self):
        steps = [{"agent": "metasploit", "config": {"module": "exploit/windows/smb/ms17_010"}}]
        approved, blocked = filter_plan_steps(steps)
        assert len(approved) == 0
        assert len(blocked) == 1
        assert "Unapproved MSF module" in blocked[0]["block_reason"]

    def test_filter_plan_steps_nuclei_blocked_tags(self):
        steps = [{"agent": "nuclei", "config": {"tags": ["dos", "network"]}}]
        approved, blocked = filter_plan_steps(steps)
        assert len(approved) == 0
        assert len(blocked) == 1

    def test_filter_plan_steps_nmap_always_approved(self):
        steps = [{"agent": "nmap", "config": {"flags": "-sV"}}]
        approved, blocked = filter_plan_steps(steps)
        assert len(approved) == 1
        assert len(blocked) == 0

    def test_filter_plan_steps_mixed(self):
        steps = [
            {"agent": "nmap", "config": {}},
            {"agent": "metasploit", "config": {"module": "auxiliary/scanner/http/dir_scanner"}},
            {"agent": "metasploit", "config": {"module": "exploit/linux/http/rails_secret_deserialization"}},
            {"agent": "nuclei", "config": {"tags": ["cve"]}},
        ]
        approved, blocked = filter_plan_steps(steps)
        assert len(approved) == 3
        assert len(blocked) == 1


# ── KillSwitch ────────────────────────────────────────────────────────────────

class TestKillSwitch:
    @pytest.mark.asyncio
    async def test_kill_switch_stops_running_containers(self):
        from app.safety.kill_switch import KillSwitch

        mock_db = AsyncMock()
        mock_execution = MagicMock()
        mock_execution.container_id = "container-abc"

        # Mock DB execute to return running executions
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_execution]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_backend = MagicMock()
        mock_backend.stop = AsyncMock()
        mock_audit = MagicMock()
        mock_audit.log = AsyncMock()

        session_id = uuid.uuid4()
        actor_id = str(uuid.uuid4())

        with patch("app.agents.backends.docker.get_docker_backend", return_value=mock_backend), \
             patch("app.safety.audit.AuditLogger", return_value=mock_audit), \
             patch("app.safety.kill_switch.get_docker_backend", return_value=mock_backend, create=True), \
             patch("app.safety.kill_switch.AuditLogger", return_value=mock_audit, create=True):
            # Patch at the import-inside-function level
            import app.agents.backends.docker as _docker_mod
            import app.safety.audit as _audit_mod
            _docker_mod.get_docker_backend = lambda: mock_backend
            _orig_audit = _audit_mod.AuditLogger
            _audit_mod.AuditLogger = lambda db: mock_audit
            try:
                ks = KillSwitch(mock_db)
                count = await ks.stop_session(session_id, actor_id)
            finally:
                _audit_mod.AuditLogger = _orig_audit

        mock_backend.stop.assert_called_once_with("container-abc")
        assert count == 1

    @pytest.mark.asyncio
    async def test_kill_switch_no_running_containers(self):
        from app.safety.kill_switch import KillSwitch

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_backend = MagicMock()
        mock_backend.stop = AsyncMock()
        mock_audit = MagicMock()
        mock_audit.log = AsyncMock()

        import app.agents.backends.docker as _docker_mod
        import app.safety.audit as _audit_mod
        _docker_mod.get_docker_backend = lambda: mock_backend
        _orig_audit = _audit_mod.AuditLogger
        _audit_mod.AuditLogger = lambda db: mock_audit
        try:
            ks = KillSwitch(mock_db)
            count = await ks.stop_session(uuid.uuid4(), "user-1")
        finally:
            _audit_mod.AuditLogger = _orig_audit

        mock_backend.stop.assert_not_called()
        assert count == 0
