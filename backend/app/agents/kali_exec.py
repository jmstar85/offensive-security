"""KaliExecAdapter — shared adapter class for the Kali coexistence path.

PR-5 wires:
  - ``build_command()`` consults ``WhitelistShim.verify`` and returns
    ``[ALLOWED_TOOLS[slug]["binary"], *args]`` on pass.
  - ``parse_output()`` dispatches to a per-slug parser plugin (mandatory —
    no generic line-mode fallback).
  - Three per-slug subclasses (KaliGobusterAdapter / KaliSqlmapAdapter /
    KaliNiktoAdapter) so the registry's adapter_cls field uniquely
    identifies the tool while all logic stays in the shared base class.

The class-level ``tool_slug`` attribute is the binding between an adapter
subclass and an ALLOWED_TOOLS entry — also used by ``parse_output`` to
look up the parser plugin.
"""
from __future__ import annotations

from app.agents.base import AgentAdapter, AgentResult, RiskLevel
from app.agents.kali_whitelist import SafetyViolation, WhitelistShim
from app.agents.parsers import get_parser
from app.safety.kali_allowlist import ALLOWED_TOOLS


class KaliExecAdapter(AgentAdapter):
    """Shared base — concrete kali_* slugs subclass and set ``tool_slug``."""

    agent_type = "kali_exec_base"
    docker_image = "osa-kali:latest"
    risk_level: RiskLevel = RiskLevel.MEDIUM
    tool_slug: str = ""  # set by subclasses to a key in ALLOWED_TOOLS

    def get_capabilities(self) -> list[str]:
        from app.agents.registry import get_tool_entry

        entry = get_tool_entry(self.agent_type)
        if entry is None:
            return []
        return list(entry.capabilities)

    def build_command(self, target: dict, config: dict) -> list[str]:
        slug = config.get("tool_slug") or self.tool_slug
        if not slug:
            raise SafetyViolation("missing_tool_slug")
        if self.tool_slug and slug != self.tool_slug:
            # Cross-slug invocation through the wrong adapter is a routing bug.
            raise SafetyViolation(
                f"slug_mismatch:adapter={self.tool_slug!r} config={slug!r}"
            )
        args = list(config.get("args", []))
        WhitelistShim.verify(slug, args, target)
        return [ALLOWED_TOOLS[slug]["binary"], *args]

    def parse_output(self, raw_output: str) -> AgentResult:
        if not self.tool_slug:
            raise NotImplementedError(
                "KaliExecAdapter requires a tool_slug; use a per-slug subclass"
            )
        return get_parser(self.tool_slug)(raw_output, self.agent_type)


class KaliGobusterAdapter(KaliExecAdapter):
    agent_type = "kali_gobuster"
    tool_slug = "gobuster"
    risk_level = RiskLevel.MEDIUM


class KaliSqlmapAdapter(KaliExecAdapter):
    agent_type = "kali_sqlmap"
    tool_slug = "sqlmap"
    risk_level = RiskLevel.HIGH


class KaliNiktoAdapter(KaliExecAdapter):
    agent_type = "kali_nikto"
    tool_slug = "nikto"
    risk_level = RiskLevel.MEDIUM
