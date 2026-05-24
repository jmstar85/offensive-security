"""KaliExecAdapter — shared adapter class for the Kali coexistence path.

A single KaliExecAdapter class backs multiple per-slug ToolEntry rows
(`kali_gobuster`, `kali_sqlmap`, `kali_nikto`) registered in PR-5. The
agent_type carries the specific Kali tool slug so safety layers can apply
per-slug tier/risk_band gating (see filter_plan_steps + risk_filter
extensions in PR-4).

PR-1 ships the skeleton. PR-5 implements `build_command()` (which calls
`WhitelistShim.verify()` before composing the command) and the mandatory
per-tool parser plugin dispatch in `parse_output()`.
"""
from __future__ import annotations

from app.agents.base import AgentAdapter, AgentResult, RiskLevel


class KaliExecAdapter(AgentAdapter):
    agent_type = "kali_exec_base"  # overridden by per-slug ToolEntry registration in PR-5
    docker_image = "osa-kali:latest"  # digest pin lands via env in PR-6
    risk_level = RiskLevel.MEDIUM

    def get_capabilities(self) -> list[str]:
        raise NotImplementedError("KaliExecAdapter.get_capabilities lands in PR-5")

    def build_command(self, target: dict, config: dict) -> list[str]:
        raise NotImplementedError("KaliExecAdapter.build_command lands in PR-5")

    def parse_output(self, raw_output: str) -> AgentResult:
        raise NotImplementedError("KaliExecAdapter.parse_output lands in PR-5")
