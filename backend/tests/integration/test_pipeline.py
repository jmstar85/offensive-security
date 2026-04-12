"""Integration tests for the orchestrator pipeline.

These tests mock external dependencies (Claude API, Docker) but use
real safety guard logic and in-memory SQLite to test the full pipeline flow.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.safety.whitelist import WhitelistValidator
from app.safety.risk_filter import RiskFilter
from app.safety.exploit_allowlist import filter_plan_steps


# ── Safety chain integration ──────────────────────────────────────────────────

class TestSafetyChainIntegration:
    """Test the full safety chain: whitelist → risk filter → exploit allowlist."""

    def test_full_chain_allows_safe_nmap_plan(self):
        whitelist = {"ip_ranges": ["192.168.1.0/24"], "domains": []}
        target = {"ip_ranges": ["192.168.1.50"], "domains": []}
        steps = [
            {"agent": "nmap", "action": "port_scan", "config": {"flags": "-sV"}},
        ]

        # Layer 1: whitelist
        validator = WhitelistValidator(whitelist)
        ok, violations = validator.validate_target(target)
        assert ok, f"Whitelist rejected valid target: {violations}"

        # Layer 2: risk filter
        rf = RiskFilter()
        allowed, blocked = rf.filter_steps(steps)
        assert len(allowed) == 1
        assert len(blocked) == 0

        # Layer 3: exploit allowlist
        approved, blocked2 = filter_plan_steps(allowed)
        assert len(approved) == 1
        assert len(blocked2) == 0

    def test_full_chain_blocks_out_of_scope_target(self):
        whitelist = {"ip_ranges": ["192.168.1.0/24"], "domains": []}
        target = {"ip_ranges": ["10.0.0.1"], "domains": []}

        validator = WhitelistValidator(whitelist)
        ok, violations = validator.validate_target(target)
        assert ok is False
        assert len(violations) > 0

    def test_full_chain_blocks_dos_step(self):
        steps = [
            {"agent": "nmap", "action": "port_scan", "config": {}},
            {"agent": "nmap", "action": "dos_flood", "config": {}},
        ]
        rf = RiskFilter()
        allowed, blocked = rf.filter_steps(steps)
        assert len(allowed) == 1
        assert len(blocked) == 1

    def test_full_chain_blocks_unapproved_msf_module(self):
        steps = [
            {"agent": "nmap", "action": "port_scan", "config": {}},
            {"agent": "metasploit", "action": "exploit", "config": {
                "module": "exploit/windows/smb/ms17_010_eternalblue"
            }},
        ]
        approved, blocked = filter_plan_steps(steps)
        assert len(approved) == 1
        assert len(blocked) == 1

    def test_full_chain_allows_approved_msf_scanner(self):
        steps = [
            {"agent": "metasploit", "action": "scan", "config": {
                "module": "auxiliary/scanner/portscan/tcp"
            }},
        ]
        approved, blocked = filter_plan_steps(steps)
        assert len(approved) == 1
        assert len(blocked) == 0


# ── Plan generation mock integration ─────────────────────────────────────────

class TestPlannerIntegration:
    """Test AttackPlanner with a mocked Claude API response."""

    def test_planner_parses_valid_json_plan(self):
        import json
        from unittest.mock import MagicMock, patch

        mock_plan = {
            "target_summary": "Test target at 192.168.1.0/24",
            "risk_level": "low",
            "steps": [
                {"order": 1, "agent": "nmap", "action": "port_scan",
                 "description": "Scan ports", "config": {"flags": "-sV -T4"}},
                {"order": 2, "agent": "nuclei", "action": "vuln_scan",
                 "description": "Check vulnerabilities", "config": {}},
            ],
        }

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=json.dumps(mock_plan))]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message

        with patch("app.orchestrator.planner.anthropic.Anthropic", return_value=mock_client), \
             patch("app.core.config.settings") as mock_settings:
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.anthropic_model = "claude-3-5-sonnet"

            from app.orchestrator.planner import AttackPlanner
            planner = AttackPlanner()
            planner._client = mock_client

            plan = planner.create_plan(
                "Scan 192.168.1.0/24",
                {"ip_ranges": ["192.168.1.0/24"], "domains": []}
            )

        assert plan["risk_level"] == "low"
        assert len(plan["steps"]) == 2
        assert plan["steps"][0]["agent"] == "nmap"

    def test_planner_strips_markdown_fences(self):
        import json
        from unittest.mock import MagicMock, patch

        mock_plan = {"target_summary": "test", "risk_level": "low", "steps": []}
        fenced = f"```json\n{json.dumps(mock_plan)}\n```"

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=fenced)]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message

        with patch("app.orchestrator.planner.anthropic.Anthropic", return_value=mock_client), \
             patch("app.core.config.settings") as mock_settings:
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.anthropic_model = "claude-3-5-sonnet"
            from app.orchestrator.planner import AttackPlanner
            planner = AttackPlanner()
            planner._client = mock_client
            plan = planner.create_plan("test", {"ip_ranges": [], "domains": []})

        assert plan["risk_level"] == "low"


# ── Report generator integration ──────────────────────────────────────────────

class TestReportGeneratorIntegration:
    @pytest.mark.asyncio
    async def test_generate_report_with_findings(self):
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.reports.generator import ReportGenerator

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        findings = [
            {"title": "Open port 22", "severity": "low", "agent_type": "nmap"},
            {"title": "CVE-2021-1234", "severity": "high", "agent_type": "nuclei"},
            {"title": "Weak creds", "severity": "critical", "agent_type": "metasploit"},
        ]
        plan = {"steps": [{"agent": "nmap"}, {"agent": "nuclei"}]}

        # PDFGenerator is imported lazily inside a try/except in generate(), so
        # patch at the module where it's defined to intercept the fresh import.
        with patch("app.reports.pdf.PDFGenerator") as mock_pdf_cls:
            mock_pdf = MagicMock()
            mock_pdf.generate = AsyncMock(return_value="/tmp/report.pdf")
            mock_pdf_cls.return_value = mock_pdf
            # Force the lazy import to pick up the patch by pre-importing the module
            import app.reports.pdf  # noqa: F401
            gen = ReportGenerator(mock_db)
            report = await gen.generate(uuid.uuid4(), findings, plan)

        assert report.risk_score == 9.0  # critical = 9.0
        assert report.findings_json["total"] == 3
        assert "critical" in report.summary
        assert "high" in report.summary

    @pytest.mark.asyncio
    async def test_generate_report_no_findings(self):
        from app.reports.generator import ReportGenerator

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        # PDF generation is non-fatal (wrapped in try/except), so no mock needed
        gen = ReportGenerator(mock_db)
        report = await gen.generate(uuid.uuid4(), [], {"steps": []})

        assert report.risk_score == 0.0
        assert "No vulnerabilities" in report.summary


# ── Event bus integration ─────────────────────────────────────────────────────

class TestEventBusIntegration:
    @pytest.mark.asyncio
    async def test_publish_and_receive(self):
        from app.core.events import EventBus

        bus = EventBus()
        session_id = str(uuid.uuid4())
        q = bus.subscribe(session_id)

        await bus.publish(session_id, {"type": "test_event", "data": "hello"})

        item = q.get_nowait()
        assert item["type"] == "test_event"
        assert item["data"] == "hello"

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_queue(self):
        from app.core.events import EventBus

        bus = EventBus()
        session_id = str(uuid.uuid4())
        q = bus.subscribe(session_id)
        bus.unsubscribe(session_id, q)

        # Publishing should not raise even with no subscribers
        await bus.publish(session_id, {"type": "orphan"})
        assert q.empty()

    @pytest.mark.asyncio
    async def test_multiple_subscribers_receive_same_event(self):
        from app.core.events import EventBus

        bus = EventBus()
        session_id = str(uuid.uuid4())
        q1 = bus.subscribe(session_id)
        q2 = bus.subscribe(session_id)

        await bus.publish(session_id, {"type": "broadcast"})

        assert not q1.empty()
        assert not q2.empty()
