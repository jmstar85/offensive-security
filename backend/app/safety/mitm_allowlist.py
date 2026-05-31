"""Single source of truth for the mitmproxy execution allowlist.

Clones the kali_allowlist structure. DENY_FLAGS and PATH_DENY_PATTERNS
are re-exported from kali_allowlist (single source). SafetyViolation is
re-exported from kali_allowlist so isinstance checks are consistent.

ALLOWED_TOOLS is defined here for mitm-specific tools only.
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

_audit_logger = logging.getLogger("osa.safety.mitm_audit")


def audit_safety_event(event: str, payload: dict[str, Any]) -> None:
    _audit_logger.info("%s %s", event, payload)
    from app.safety.audit import emit_kali_metric
    emit_kali_metric(event, payload)


_EMPTY_RX = r"^$"
_PORT_RX = r"^\d{1,5}$"
_ADDON_PATH_RX = r"^/addons/[A-Za-z0-9_\-./]+$"

ALLOWED_TOOLS: dict[str, dict[str, Any]] = {
    "mitm_proxy": {
        "binary": "/usr/bin/mitmdump",
        "arg_validators": {
            "--mode": r"^(regular|transparent|socks5|reverse:.+|upstream:.+)$",
            "--listen-port": _PORT_RX,
            "--scripts": _ADDON_PATH_RX,
            "--ssl-insecure": _EMPTY_RX,
            "--no-http2": _EMPTY_RX,
        },
        "value_flags": frozenset({
            "--mode",
            "--listen-port",
            "--scripts",
        }),
        "cap_add": (),
        "risk_band_score": 0.6,
        "tier": "mid_active",
        "is_destructive_capable": False,
    },
    "mitm_addon_run": {
        "binary": "/usr/bin/mitmdump",
        "arg_validators": {},
        "value_flags": frozenset(),
        "cap_add": (),
        "risk_band_score": 0.4,
        "tier": "mid_active",
        "is_destructive_capable": False,
    },
}


def _emit_block(slug: str | None, args: list[str], reason: str) -> None:
    audit_safety_event(
        "mitm_exec.shim_block",
        {"slug": slug, "args": _redact_args(args), "reason": reason},
    )


def verify_mitm_args(
    slug: str | None,
    args: list[str],
    target: dict | None = None,
) -> None:
    """Core verification for mitm tools. Raises SafetyViolation on any breach."""
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


def mitm_exec_allowlist(
    agent: str,
    tool_slug: str | None,
    args: list[str],
) -> tuple[bool, str]:
    """Gate for mitm agents. Non-mitm agents pass through unconditionally."""
    if not isinstance(agent, str) or not agent.startswith("mitm_"):
        return (True, "")
    try:
        verify_mitm_args(tool_slug, list(args))
    except SafetyViolation as exc:
        return (False, str(exc))
    return (True, "")
