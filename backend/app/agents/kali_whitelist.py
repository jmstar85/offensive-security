"""WhitelistShim — call-time command verification for the Kali path.

This module deliberately holds NO whitelist data. The single source of
truth is ``backend/app/safety/kali_allowlist.py``. The AST guard in
``tests/unit/test_kali_allowlist_single_source.py`` fails the build if
``ALLOWED_TOOLS`` is redefined here or if Kali binary path literals appear
outside the safety module.

PR-3 implements ``verify()`` as a thin facade over
``safety.kali_allowlist.verify_kali_args`` so both the call-time shim and
the plan-time gate (``kali_exec_allowlist``) share one verifier.
"""
from __future__ import annotations

from app.safety.kali_allowlist import (  # noqa: F401 — re-exported for callers
    ALLOWED_TOOLS,
    DENY_FLAGS,
    KALI_ALLOWED_CAPS,
    PATH_DENY_PATTERNS,
    SafetyViolation,
    verify_kali_args,
)


class WhitelistShim:
    @staticmethod
    def verify(slug: str, args: list[str], target: dict | None = None) -> None:
        verify_kali_args(slug, args, target)
