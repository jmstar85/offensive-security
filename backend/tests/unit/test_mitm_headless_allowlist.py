"""Unit tests for mitm_allowlist and headless_allowlist."""
from __future__ import annotations

import pytest

from app.safety.kali_allowlist import (
    DENY_FLAGS as KALI_DENY_FLAGS,
    SafetyViolation as KaliSafetyViolation,
)
from app.safety.mitm_allowlist import (
    DENY_FLAGS as MITM_DENY_FLAGS,
    SafetyViolation as MitmSafetyViolation,
    verify_mitm_args,
    mitm_exec_allowlist,
)
from app.safety.headless_allowlist import (
    SafetyViolation as HeadlessSafetyViolation,
    verify_headless_args,
    headless_exec_allowlist,
)


# ── mitm allowlist ─────────────────────────────────────────────────────────────

def test_mitm_allowlist_blocks_deny_flags():
    with pytest.raises(MitmSafetyViolation, match="deny_flag"):
        verify_mitm_args("mitm_proxy", ["--proxy", "http://evil.example.com"])


def test_mitm_allowlist_blocks_path_traversal():
    with pytest.raises(MitmSafetyViolation):
        verify_mitm_args("mitm_proxy", ["--scripts", "/etc/passwd"])


def test_mitm_allowlist_passes_clean_args():
    # Should not raise.
    verify_mitm_args("mitm_proxy", [
        "--mode", "regular",
        "--listen-port", "8080",
        "--ssl-insecure",
    ])


def test_mitm_allowlist_blocks_unknown_flag():
    with pytest.raises(MitmSafetyViolation, match="unknown_flag"):
        verify_mitm_args("mitm_proxy", ["--evil-flag"])


def test_mitm_allowlist_addon_run_no_args():
    # mitm_addon_run accepts no CLI args.
    verify_mitm_args("mitm_addon_run", [])


def test_mitm_exec_allowlist_non_mitm_agent_passes_through():
    ok, reason = mitm_exec_allowlist("kali_gobuster", "gobuster", ["dir", "--url", "http://x.com"])
    assert ok is True
    assert reason == ""


def test_mitm_exec_allowlist_blocks_bad_slug():
    ok, reason = mitm_exec_allowlist("mitm_proxy", "unknown_slug", [])
    assert ok is False
    assert "unknown_slug" in reason


# ── headless allowlist ─────────────────────────────────────────────────────────

def test_headless_allowlist_blocks_unknown_probe_type():
    with pytest.raises(HeadlessSafetyViolation, match="invalid_value"):
        verify_headless_args("headless_browser", [
            "--probe-type", "evil_probe",
            "--target", "http://example.com",
        ])


def test_headless_allowlist_passes_clean_args():
    verify_headless_args("headless_browser", [
        "--probe-type", "dom_xss",
        "--target", "http://example.com",
        "--timeout", "30",
    ])


def test_headless_allowlist_blocks_unknown_flag():
    with pytest.raises(HeadlessSafetyViolation, match="unknown_flag"):
        verify_headless_args("headless_browser", ["--output", "/work/out.json"])


def test_headless_exec_allowlist_non_headless_agent_passes_through():
    ok, reason = headless_exec_allowlist("kali_nikto", "nikto", [])
    assert ok is True
    assert reason == ""


# ── singleton / re-export assertions ──────────────────────────────────────────

def test_mitm_safetyviolation_is_kali_safetyviolation():
    assert MitmSafetyViolation is KaliSafetyViolation


def test_headless_safetyviolation_is_kali_safetyviolation():
    assert HeadlessSafetyViolation is KaliSafetyViolation


def test_deny_flags_is_kali_singleton():
    assert MITM_DENY_FLAGS is KALI_DENY_FLAGS
