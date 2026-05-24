"""Single source of truth for the Kali-tool execution allowlist.

This module is the ONLY place where the Kali tool whitelist is defined.
Other modules (agents/kali_whitelist.py, agents/kali_exec.py,
safety/exploit_allowlist.py, safety/risk_filter.py) import from here.

An AST-based unit test (tests/unit/test_kali_allowlist_single_source.py)
prevents redefinition of ALLOWED_TOOLS or hard-coded Kali binary paths
elsewhere in the backend/agents tree.

v1 ships with an EMPTY allowlist and `KALI_ALLOWED_CAPS = frozenset()`.
PR-3 populates the three v1 tools (gobuster, sqlmap, nikto).
"""
from __future__ import annotations


ALLOWED_TOOLS: dict[str, dict] = {}

KALI_ALLOWED_CAPS: frozenset[str] = frozenset()


def kali_exec_allowlist(
    agent: str,
    tool_slug: str | None,
    args: list[str],
) -> tuple[bool, str]:
    """Gate function consulted by safety/exploit_allowlist.filter_plan_steps.

    PR-1 stub: always rejects. PR-3 implements per-tool arg validation,
    deny-flag set, and path denylist using ALLOWED_TOOLS.
    """
    return (False, "not implemented")
