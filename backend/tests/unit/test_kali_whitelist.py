"""PR-3 unit tests — WhitelistShim + per-tool ALLOWED_TOOLS.

Coverage matrix (US-PR-3 acceptance):
  - 2 slug edge cases (None, unknown)
  - 16 DENY_FLAGS cases (one per flag, mixed across tools)
  - 8 PATH_DENY_PATTERNS cases (each prefix + each token)
  - 6 invalid arg-value regex cases (2 per tool)
  - 9 positive cases (3 per tool)
  - 1 missing mode-arg gobuster case
  - audit emission contract on rejection
Total: 42 negative + 9 positive = 51 assertions.
"""
from __future__ import annotations

import pytest

from app.agents.kali_whitelist import WhitelistShim
from app.safety import kali_allowlist
from app.safety.kali_allowlist import (
    ALLOWED_TOOLS,
    DENY_FLAGS,
    PATH_DENY_PATTERNS,
    SafetyViolation,
    verify_kali_args,
)


# --- Audit capture fixture ----------------------------------------------------

@pytest.fixture
def audit_events(monkeypatch):
    captured: list[tuple[str, dict]] = []

    def fake_emit(event: str, payload: dict) -> None:
        captured.append((event, dict(payload)))

    monkeypatch.setattr(kali_allowlist, "audit_safety_event", fake_emit)
    return captured


# --- Slug edge cases ----------------------------------------------------------

def test_missing_slug_rejected(audit_events):
    with pytest.raises(SafetyViolation, match="unknown_slug"):
        verify_kali_args(None, [])
    assert audit_events[-1][0] == "kali_exec.shim_block"
    assert audit_events[-1][1]["reason"].startswith("unknown_slug")


def test_unknown_slug_rejected(audit_events):
    with pytest.raises(SafetyViolation, match="unknown_slug"):
        verify_kali_args("hashcat", ["--help"])
    assert audit_events[-1][1]["reason"].startswith("unknown_slug")


def test_unknown_slug_via_shim(audit_events):
    with pytest.raises(SafetyViolation):
        WhitelistShim.verify("nessus", [])


# --- DENY_FLAGS exhaustive coverage (16 cases) -------------------------------

# Per-tool tail args used to construct otherwise-valid invocations into which
# the deny flag is injected. gobuster needs a mode; sqlmap/nikto are flag-only.
_DENY_FLAG_CASES: list[tuple[str, list[str]]] = [
    # (slug, args_template_with_deny_flag_injected)
    ("sqlmap", ["--proxy=http://evil/", "--batch"]),
    ("gobuster", ["dir", "-x", "/var/log"]),
    ("sqlmap", ["--http-proxy=http://evil/", "--batch"]),
    ("sqlmap", ["--https-proxy=http://evil/", "--batch"]),
    ("sqlmap", ["--auth-cred=admin:hunter2"]),
    ("sqlmap", ["--cookie-jar=/tmp/c.jar"]),
    ("sqlmap", ["--load-cookies=/tmp/c.jar"]),
    ("gobuster", ["dir", "--config=/work/cfg.yml"]),
    ("sqlmap", ["--rc-file=/tmp/rc"]),
    ("sqlmap", ["--shell"]),
    ("sqlmap", ["--os-shell"]),
    ("sqlmap", ["--sql-shell"]),
    ("sqlmap", ["--file-read=/etc/passwd"]),
    ("sqlmap", ["--file-write=/tmp/x"]),
    ("sqlmap", ["--read-file=/etc/passwd"]),
    ("sqlmap", ["--write-file=/tmp/x"]),
]


@pytest.mark.parametrize("slug,args", _DENY_FLAG_CASES)
def test_deny_flag_rejected(audit_events, slug, args):
    with pytest.raises(SafetyViolation) as exc:
        verify_kali_args(slug, args)
    assert "deny_flag" in str(exc.value) or "unknown_flag" not in str(exc.value)
    assert audit_events[-1][1]["reason"].startswith("deny_flag:")


def test_deny_flag_set_is_complete():
    # Sanity: the parametrized cases cover every DENY_FLAGS entry exactly once.
    covered = set()
    for _slug, args in _DENY_FLAG_CASES:
        for a in args:
            flag = a.split("=", 1)[0]
            if flag in DENY_FLAGS:
                covered.add(flag)
    assert covered == set(DENY_FLAGS), (
        f"DENY_FLAGS not all exercised by parametrized matrix; missing="
        f"{set(DENY_FLAGS) - covered}"
    )


# --- PATH_DENY_PATTERNS coverage (8 cases) -----------------------------------

_PATH_DENY_CASES: list[tuple[str, list[str]]] = [
    # /etc/, /proc/, /sys/, /var/run/, /root/, /.ssh/ as flag values
    ("gobuster", ["dir", "--wordlist", "/etc/shadow"]),
    ("gobuster", ["dir", "--output", "/proc/self/environ"]),
    ("nikto", ["-output", "/sys/class/net/eth0/address"]),
    ("nikto", ["-output", "/var/run/docker.sock"]),
    ("sqlmap", ["--output-dir", "/root/.config"]),
    ("sqlmap", ["--output-dir", "/.ssh/id_rsa"]),
    # token patterns: $HOME and ..
    ("sqlmap", ["--output-dir", "$HOME/loot"]),
    ("gobuster", ["dir", "--output", "/work/../etc/passwd"]),
]


@pytest.mark.parametrize("slug,args", _PATH_DENY_CASES)
def test_path_deny_pattern_rejected(audit_events, slug, args):
    with pytest.raises(SafetyViolation) as exc:
        verify_kali_args(slug, args)
    reason = str(exc.value)
    assert reason.startswith(("path_deny_prefix:", "path_deny_token:"))
    assert audit_events[-1][1]["reason"] == reason


def test_path_deny_patterns_constant_count():
    assert len(PATH_DENY_PATTERNS) == 8


# --- Invalid arg-value regex (≥2 per tool) -----------------------------------

@pytest.mark.parametrize("slug,args", [
    ("gobuster", ["dir", "--threads", "9999"]),    # over 3 digits
    ("gobuster", ["dir", "--url", "ftp://evil"]),   # not http(s)
    ("sqlmap", ["--level", "9"]),                    # only 1-5
    ("sqlmap", ["--risk", "0"]),                     # only 1-3
    ("nikto", ["-Format", "binary"]),                # not in enum
    ("nikto", ["-p", "abc"]),                        # not a port
])
def test_invalid_regex_rejected(audit_events, slug, args):
    with pytest.raises(SafetyViolation) as exc:
        verify_kali_args(slug, args)
    assert str(exc.value).startswith("invalid_value:")


# --- Unknown flag rejection ---------------------------------------------------

def test_unknown_flag_rejected(audit_events):
    with pytest.raises(SafetyViolation) as exc:
        verify_kali_args("gobuster", ["dir", "--totally-fake"])
    assert str(exc.value).startswith("unknown_flag:")


# --- Mode-gate edge cases (gobuster) -----------------------------------------

def test_gobuster_missing_mode_rejected(audit_events):
    with pytest.raises(SafetyViolation) as exc:
        verify_kali_args("gobuster", [])
    assert str(exc.value).startswith("missing_mode_for:")


def test_gobuster_invalid_mode_rejected(audit_events):
    with pytest.raises(SafetyViolation) as exc:
        verify_kali_args("gobuster", ["scan"])
    assert str(exc.value).startswith("invalid_mode:")


def test_gobuster_unexpected_positional_after_mode(audit_events):
    with pytest.raises(SafetyViolation) as exc:
        verify_kali_args("gobuster", ["dir", "stuff"])
    assert str(exc.value).startswith("unexpected_positional:")


# --- Positive cases (≥3 per tool) --------------------------------------------

@pytest.mark.parametrize("slug,args", [
    # gobuster — 3 positive
    ("gobuster", ["dir", "--url", "http://target/", "--wordlist", "/wordlists/common.txt"]),
    ("gobuster", ["dns", "-u", "http://target/", "-w", "/usr/share/wordlists/subs.txt", "--threads", "20"]),
    ("gobuster", ["vhost", "--url=http://target/", "--wordlist=/wordlists/vhosts.txt", "--quiet"]),
    # sqlmap — 3 positive
    ("sqlmap", ["-u", "http://target/q?id=1", "--batch"]),
    ("sqlmap", ["--url=http://target/q", "--level=3", "--risk=2", "--technique=BEU"]),
    ("sqlmap", ["-u", "http://target/q?id=1", "--batch", "--output-dir", "/work/sqlmap-out", "--random-agent"]),
    # nikto — 3 positive
    ("nikto", ["-h", "http://target/", "-Format", "json"]),
    ("nikto", ["-host=http://target/", "-Tuning=1,2,3,x"]),
    ("nikto", ["-h", "http://target/", "-output", "/work/nikto.json", "-nointeractive"]),
])
def test_positive_invocations_pass(audit_events, slug, args):
    # Must not raise; must not emit shim_block events.
    verify_kali_args(slug, args)
    block_events = [e for e in audit_events if e[1]["reason"].startswith(
        ("deny_flag:", "path_deny", "invalid_value:", "unknown_flag:", "unknown_slug:")
    )]
    assert not block_events, f"unexpected blocks: {block_events}"


# --- WhitelistShim.verify facade --------------------------------------------

def test_whitelist_shim_passes_positive():
    WhitelistShim.verify("gobuster", ["dir", "-u", "http://t/", "-w", "/wordlists/c.txt"])


def test_whitelist_shim_rejects_deny_flag(audit_events):
    with pytest.raises(SafetyViolation):
        WhitelistShim.verify("sqlmap", ["--os-shell"])


# --- Audit emission contract ------------------------------------------------

def test_audit_payload_shape_on_block(audit_events):
    with pytest.raises(SafetyViolation):
        verify_kali_args("sqlmap", ["--os-shell"])
    event, payload = audit_events[-1]
    assert event == "kali_exec.shim_block"
    assert set(payload.keys()) == {"slug", "args", "reason"}
    assert payload["slug"] == "sqlmap"
    assert payload["args"] == ["--os-shell"]


def test_audit_args_redaction_truncates_long_values(audit_events):
    long_val = "A" * 200
    with pytest.raises(SafetyViolation):
        verify_kali_args("gobuster", ["dir", "--url", long_val])
    payload = audit_events[-1][1]
    redacted = payload["args"]
    assert any("<truncated>" in str(x) for x in redacted)


# --- ALLOWED_TOOLS schema invariants ----------------------------------------

def test_allowed_tools_has_exactly_three_entries():
    assert set(ALLOWED_TOOLS.keys()) == {"gobuster", "sqlmap", "nikto"}


@pytest.mark.parametrize("slug,expected_score,expected_tier,expected_destructive", [
    ("gobuster", 0.5, "active_recon", False),
    ("sqlmap",   0.8, "active_exploit", True),
    ("nikto",    0.5, "active_recon", False),
])
def test_allowed_tool_entry_required_fields(slug, expected_score, expected_tier, expected_destructive):
    entry = ALLOWED_TOOLS[slug]
    assert entry["binary"].startswith("/usr/bin/")
    assert isinstance(entry["arg_validators"], dict) and entry["arg_validators"]
    assert tuple(entry["cap_add"]) == ()
    assert entry["risk_band_score"] == expected_score
    assert entry["tier"] == expected_tier
    assert entry["is_destructive_capable"] is expected_destructive


def test_gobuster_has_mode_whitelist():
    assert ALLOWED_TOOLS["gobuster"]["mode_whitelist"] == frozenset({"dir", "dns", "vhost"})


# --- kali_exec_allowlist gate behavior (consumed by PR-4) ---------------------

def test_kali_exec_allowlist_passthrough_for_non_kali_agent():
    from app.safety.kali_allowlist import kali_exec_allowlist
    ok, reason = kali_exec_allowlist("nmap", None, [])
    assert ok and reason == ""


def test_kali_exec_allowlist_blocks_deny_flag():
    from app.safety.kali_allowlist import kali_exec_allowlist
    ok, reason = kali_exec_allowlist("kali_sqlmap", "sqlmap", ["--os-shell"])
    assert not ok and reason.startswith("deny_flag:")


def test_kali_exec_allowlist_passes_valid_invocation():
    from app.safety.kali_allowlist import kali_exec_allowlist
    ok, reason = kali_exec_allowlist(
        "kali_gobuster", "gobuster",
        ["dir", "-u", "http://t/", "-w", "/wordlists/c.txt"],
    )
    assert ok and reason == ""
