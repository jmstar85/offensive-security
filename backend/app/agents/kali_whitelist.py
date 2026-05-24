"""WhitelistShim — call-time command verification for the Kali path.

This module deliberately holds NO whitelist data. The single source of
truth is `backend/app/safety/kali_allowlist.py`. The AST guard in
`tests/unit/test_kali_allowlist_single_source.py` fails the build if
`ALLOWED_TOOLS` is redefined here or if Kali binary path literals appear
outside the safety module.

PR-1 ships the skeleton; PR-3 implements `verify()` with per-tool arg
validators, the deny-flag set, and the path denylist.
"""
from __future__ import annotations

from app.safety.kali_allowlist import (  # noqa: F401 — re-export for agent path
    ALLOWED_TOOLS,
    KALI_ALLOWED_CAPS,
)


class SafetyViolation(Exception):
    """Raised when WhitelistShim rejects a (tool_slug, args) pair."""


class WhitelistShim:
    @staticmethod
    def verify(slug: str, args: list[str], target: dict | None = None) -> None:
        raise NotImplementedError("WhitelistShim.verify lands in PR-3")
