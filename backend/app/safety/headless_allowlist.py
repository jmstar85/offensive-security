"""Single source of truth for the headless browser execution allowlist.

Clones the kali_allowlist structure. DENY_FLAGS and PATH_DENY_PATTERNS
are re-exported from kali_allowlist (single source). SafetyViolation is
re-exported from kali_allowlist so isinstance checks are consistent.

ALLOWED_TOOLS is defined here for headless-specific tools only.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.safety.kali_allowlist import (
    DENY_FLAGS as DENY_FLAGS,
    PATH_DENY_PATTERNS as PATH_DENY_PATTERNS,
    SafetyViolation as SafetyViolation,
    _path_violation,
    _redact_args,
    _split_flag,
)

_audit_logger = logging.getLogger("osa.safety.headless_audit")


def audit_safety_event(event: str, payload: dict[str, Any]) -> None:
    _audit_logger.info("%s %s", event, payload)
    from app.safety.audit import emit_kali_metric
    emit_kali_metric(event, payload)


_EMPTY_RX = r"^$"
_INT_RX = r"^\d+$"
_URL_RX = r"^https?://[A-Za-z0-9._\-:/@%?&=#+~]+$"

ALLOWED_TOOLS: dict[str, dict[str, Any]] = {
    "headless_browser": {
        "binary": "/home/osa/harness/probe_runner.js",
        "arg_validators": {
            "--probe-type": r"^(dom_xss|csrf_form|ssrf)$",
            "--target": _URL_RX,
            "--timeout": _INT_RX,
        },
        "value_flags": frozenset({
            "--probe-type",
            "--target",
            "--timeout",
        }),
        "cap_add": (),
        "risk_band_score": 0.6,
        "tier": "mid_active",
        "is_destructive_capable": False,
    },
}


def _emit_block(slug: str | None, args: list[str], reason: str) -> None:
    audit_safety_event(
        "headless_exec.shim_block",
        {"slug": slug, "args": _redact_args(args), "reason": reason},
    )


def verify_headless_args(
    slug: str | None,
    args: list[str],
    target: dict | None = None,
) -> None:
    """Core verification for headless tools. Raises SafetyViolation on any breach."""
    if not slug or slug not in ALLOWED_TOOLS:
        reason = f"unknown_slug:{slug!r}"
        _emit_block(slug, args, reason)
        raise SafetyViolation(reason)

    entry = ALLOWED_TOOLS[slug]
    validators: dict[str, str] = entry["arg_validators"]
    value_flags: frozenset[str] = entry.get("value_flags", frozenset())

    def block(reason: str) -> None:
        _emit_block(slug, args, reason)
        raise SafetyViolation(reason)

    i = 0
    while i < len(args):
        raw = args[i]
        if not isinstance(raw, str):
            block(f"non_string_arg:{type(raw).__name__}")

        pv = _path_violation(raw)
        if pv is not None:
            block(pv)

        if raw.startswith("-"):
            flag, embedded = _split_flag(raw)
            if flag in DENY_FLAGS:
                block(f"deny_flag:{flag}")
            if flag not in validators:
                block(f"unknown_flag:{flag}")
            if embedded is not None:
                value: str = embedded
                pv2 = _path_violation(value)
                if pv2 is not None:
                    block(pv2)
            elif flag in value_flags:
                if i + 1 >= len(args):
                    block(f"missing_value_for:{flag}")
                value = args[i + 1]
                if not isinstance(value, str):
                    block(f"non_string_arg:{type(value).__name__}")
                pv2 = _path_violation(value)
                if pv2 is not None:
                    block(pv2)
                i += 1
            else:
                value = ""
            if re.fullmatch(validators[flag], value) is None:
                block(f"invalid_value:{flag}={value!r}")
        else:
            block(f"unexpected_positional:{raw!r}")
        i += 1


def headless_exec_allowlist(
    agent: str,
    tool_slug: str | None,
    args: list[str],
) -> tuple[bool, str]:
    """Gate for headless agents. Non-headless agents pass through unconditionally."""
    if not isinstance(agent, str) or not agent.startswith("headless_"):
        return (True, "")
    try:
        verify_headless_args(tool_slug, list(args))
    except SafetyViolation as exc:
        return (False, str(exc))
    return (True, "")
