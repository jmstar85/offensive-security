"""Single source of truth for the Kali-tool execution allowlist.

This module is the ONLY place where the Kali tool whitelist is defined.
Other modules (agents/kali_whitelist.py, agents/kali_exec.py,
safety/exploit_allowlist.py, safety/risk_filter.py) import from here.

An AST-based unit test (tests/unit/test_kali_allowlist_single_source.py)
prevents redefinition of ALLOWED_TOOLS or hard-coded Kali binary paths
elsewhere in the backend/agents tree.

PR-3 lands:
  - DENY_FLAGS (cross-tool deny-flag set)
  - PATH_DENY_PATTERNS (path traversal / sensitive-prefix denylist)
  - ALLOWED_TOOLS for gobuster / sqlmap / nikto with per-flag regex validators
  - verify_kali_args() core verification + SafetyViolation
  - kali_exec_allowlist() gate consumed by PR-4 safety-layer extension
"""
from __future__ import annotations

import logging
import re
from typing import Any

_audit_logger = logging.getLogger("osa.safety.kali_audit")


def audit_safety_event(event: str, payload: dict[str, Any]) -> None:
    """Module-level safety-event emitter.

    PR-3 ships a logging-only implementation. PR-8 extends this to
    Prometheus counters + DB persistence. Tests monkeypatch this symbol
    to capture emissions deterministically.
    """
    _audit_logger.info("%s %s", event, payload)


class SafetyViolation(Exception):
    """Raised by verify_kali_args / WhitelistShim on any whitelist breach."""


# Cross-tool deny-flag set — proxy / credential-exfil / shell-escape vectors.
DENY_FLAGS: frozenset[str] = frozenset({
    "--proxy",
    "-x",
    "--http-proxy",
    "--https-proxy",
    "--auth-cred",
    "--cookie-jar",
    "--load-cookies",
    "--config",
    "--rc-file",
    "--shell",
    "--os-shell",
    "--sql-shell",
    "--file-read",
    "--file-write",
    "--read-file",
    "--write-file",
})

# Path patterns rejected anywhere in args (positional or flag value).
_PATH_PREFIX_DENY: tuple[str, ...] = (
    "/etc/",
    "/proc/",
    "/sys/",
    "/var/run/",
    "/root/",
    "/.ssh/",
)
_PATH_TOKEN_DENY: tuple[str, ...] = ("$HOME", "..")

# Public view consumed by tests and runbook.
PATH_DENY_PATTERNS: tuple[str, ...] = _PATH_PREFIX_DENY + _PATH_TOKEN_DENY


def _path_violation(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    for prefix in _PATH_PREFIX_DENY:
        if value.startswith(prefix):
            return f"path_deny_prefix:{prefix}"
    if value == "$HOME" or value.startswith("$HOME/") or "$HOME" in value:
        return "path_deny_token:$HOME"
    # `..` only flagged as a path component to avoid false positives on
    # innocuous CLI substrings.
    if (
        value == ".."
        or value.startswith("../")
        or "/../" in value
        or value.endswith("/..")
    ):
        return "path_deny_token:.."
    return None


KALI_ALLOWED_CAPS: frozenset[str] = frozenset()


# Regex building blocks --------------------------------------------------------
_URL_RX = r"^https?://[A-Za-z0-9._\-:/@%?&=#+~]+$"
_WORK_PATH_RX = r"^/work/[A-Za-z0-9_\-./]+$"
_WORDLIST_PATH_RX = r"^/(work|wordlists|usr/share/wordlists)/[A-Za-z0-9_\-./]+$"
_PORT_LIST_RX = r"^\d{1,5}(,\d{1,5})*$"
_INT_RX = r"^\d+$"
_SMALL_INT_RX = r"^\d{1,3}$"
_EMPTY_RX = r"^$"


# Per-tool entries ------------------------------------------------------------
# Schema:
#   binary               absolute path inside osa-kali image
#   arg_validators       flag -> value regex (value matched with re.fullmatch)
#   value_flags          subset of arg_validators where the value lives in the
#                        NEXT argv element (rather than --flag=value form)
#   mode_whitelist       optional set of allowed first-positional modes
#   cap_add              per-tool extra Linux caps (must be subset of KALI_ALLOWED_CAPS)
#   risk_band_score      numeric weight consumed by risk_filter (PR-4)
#   tier                 registry tier name (PR-5)
#   is_destructive_capable  whether the tool can mutate target state
ALLOWED_TOOLS: dict[str, dict[str, Any]] = {
    "gobuster": {
        "binary": "/usr/bin/gobuster",
        "mode_whitelist": frozenset({"dir", "dns", "vhost"}),
        "arg_validators": {
            "--url": _URL_RX,
            "-u": _URL_RX,
            "--wordlist": _WORDLIST_PATH_RX,
            "-w": _WORDLIST_PATH_RX,
            "--threads": _SMALL_INT_RX,
            "-t": _SMALL_INT_RX,
            "--timeout": r"^\d+(\.\d+)?(s|ms)?$",
            "--output": _WORK_PATH_RX,
            "-o": _WORK_PATH_RX,
            "--status-codes": r"^[\d,]+$",
            "-s": r"^[\d,]+$",
            "--extensions": r"^[A-Za-z0-9,.]+$",
            "--no-color": _EMPTY_RX,
            "--no-error": _EMPTY_RX,
            "--quiet": _EMPTY_RX,
            "-q": _EMPTY_RX,
        },
        "value_flags": frozenset({
            "--url", "-u", "--wordlist", "-w", "--threads", "-t",
            "--timeout", "--output", "-o", "--status-codes", "-s",
            "--extensions",
        }),
        "cap_add": (),
        "risk_band_score": 0.5,
        "tier": "active_recon",
        "is_destructive_capable": False,
    },
    "sqlmap": {
        "binary": "/usr/bin/sqlmap",
        "arg_validators": {
            "-u": _URL_RX,
            "--url": _URL_RX,
            "--data": r"^[A-Za-z0-9&=._\-+/%~]+$",
            "--level": r"^[1-5]$",
            "--risk": r"^[1-3]$",
            "--batch": _EMPTY_RX,
            "--threads": r"^\d{1,2}$",
            "--technique": r"^[BEUSTQ]+$",
            "--dbms": r"^[A-Za-z0-9_]+$",
            "--output-dir": _WORK_PATH_RX,
            "--timeout": _INT_RX,
            "--retries": _INT_RX,
            "--random-agent": _EMPTY_RX,
            "--flush-session": _EMPTY_RX,
        },
        "value_flags": frozenset({
            "-u", "--url", "--data", "--level", "--risk", "--threads",
            "--technique", "--dbms", "--output-dir", "--timeout", "--retries",
        }),
        "cap_add": (),
        "risk_band_score": 0.8,
        "tier": "active_exploit",
        "is_destructive_capable": True,
    },
    "nikto": {
        "binary": "/usr/bin/nikto",
        "arg_validators": {
            "-h": _URL_RX,
            "-host": _URL_RX,
            "-p": _PORT_LIST_RX,
            "-port": _PORT_LIST_RX,
            "-Format": r"^(json|csv|txt|xml|htm)$",
            "-output": _WORK_PATH_RX,
            "-o": _WORK_PATH_RX,
            "-Tuning": r"^[\dx,]+$",
            "-Plugins": r"^[A-Za-z0-9_,]+$",
            "-nointeractive": _EMPTY_RX,
            "-ask": r"^(no|yes|auto)$",
        },
        "value_flags": frozenset({
            "-h", "-host", "-p", "-port", "-Format", "-output", "-o",
            "-Tuning", "-Plugins", "-ask",
        }),
        "cap_add": (),
        "risk_band_score": 0.5,
        "tier": "active_recon",
        "is_destructive_capable": False,
    },
}


def _redact_args(args: list[str]) -> list[str]:
    """Cap each arg at 128 chars for audit emission."""
    redacted: list[str] = []
    for a in args:
        if not isinstance(a, str):
            redacted.append(repr(a))
            continue
        redacted.append(a if len(a) <= 128 else f"{a[:120]}…<truncated>")
    return redacted


def _split_flag(arg: str) -> tuple[str, str | None]:
    """Return (flag, embedded_value or None) for `--flag=value` form."""
    if arg.startswith("-") and "=" in arg:
        flag, _, value = arg.partition("=")
        return flag, value
    return arg, None


def _emit_block(slug: str | None, args: list[str], reason: str) -> None:
    audit_safety_event(
        "kali_exec.shim_block",
        {"slug": slug, "args": _redact_args(args), "reason": reason},
    )


def verify_kali_args(
    slug: str | None,
    args: list[str],
    target: dict | None = None,
) -> None:
    """Core verification. Raises SafetyViolation on any breach.

    Emits a ``kali_exec.shim_block`` audit event immediately before raising
    so the rejection is observable even when SafetyViolation is caught.
    """
    if not slug or slug not in ALLOWED_TOOLS:
        reason = f"unknown_slug:{slug!r}"
        _emit_block(slug, args, reason)
        raise SafetyViolation(reason)

    entry = ALLOWED_TOOLS[slug]
    validators: dict[str, str] = entry["arg_validators"]
    value_flags: frozenset[str] = entry.get("value_flags", frozenset())
    mode_whitelist = entry.get("mode_whitelist")

    def block(reason: str) -> None:
        _emit_block(slug, args, reason)
        raise SafetyViolation(reason)

    # Mode gate (gobuster: first positional must be in {dir, dns, vhost}).
    start_index = 0
    if mode_whitelist is not None:
        if not args:
            block(f"missing_mode_for:{slug}")
        first = args[0]
        if not isinstance(first, str):
            block(f"non_string_arg:{type(first).__name__}")
        if first not in mode_whitelist:
            block(f"invalid_mode:{first!r} not in {sorted(mode_whitelist)}")
        start_index = 1

    i = start_index
    while i < len(args):
        raw = args[i]
        if not isinstance(raw, str):
            block(f"non_string_arg:{type(raw).__name__}")

        # Path-deny check fires on every arg (flag or value).
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
            # Bare positional after the (optional) mode arg — reject for v1.
            block(f"unexpected_positional:{raw!r}")
        i += 1


def kali_exec_allowlist(
    agent: str,
    tool_slug: str | None,
    args: list[str],
) -> tuple[bool, str]:
    """Gate consumed by PR-4 safety-layer extension.

    Non-kali agents pass through unconditionally. Kali agents are routed
    through ``verify_kali_args`` and any SafetyViolation is converted to
    (False, reason).
    """
    if not isinstance(agent, str) or not agent.startswith("kali_"):
        return (True, "")
    try:
        verify_kali_args(tool_slug, list(args))
    except SafetyViolation as exc:
        return (False, str(exc))
    return (True, "")
