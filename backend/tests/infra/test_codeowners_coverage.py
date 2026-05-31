"""
Assert that every security-critical path in GUARDED_PATHS is covered by
at least one CODEOWNERS rule owned by @security-reviewer or @security-team.
"""
import fnmatch
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CODEOWNERS_FILE = REPO_ROOT / ".github" / "CODEOWNERS"

GUARDED_PATHS = [
    "backend/app/safety/exploit_allowlist.py",
    "backend/app/safety/kali_allowlist.py",
    "backend/app/safety/audit_kali.py",
    "backend/app/safety/risk_filter.py",
    "backend/app/safety/conversation_scrubber.py",
    "backend/app/agents/backends/docker.py",
    "backend/app/agents/backends/kali.py",
    "backend/app/infra/socket_proxy_filter.py",
    "backend/app/core/feature_flag_validator.py",
    "backend/app/roles/seed_xbow.py",
    "backend/app/orchestrator/coordinator.py",
    "docker/kali/kali.env",
    "docker/kali/kali-apt-snapshot.env",
    "docker/mitmproxy/Dockerfile",
    "docker/headless-browser/Dockerfile",
    "docker/interactsh/Dockerfile",
]

SECURITY_OWNERS = {"@security-reviewer", "@security-team"}


def _parse_codeowners():
    """Return list of (pattern, owners_set) tuples, skipping comments/blanks."""
    rules = []
    with open(CODEOWNERS_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            pattern = parts[0]
            owners = set(parts[1:])
            rules.append((pattern, owners))
    return rules


def _matches(pattern: str, path: str) -> bool:
    """Return True if CODEOWNERS pattern matches the given path string."""
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return path.startswith(prefix + "/") or path == prefix
    if "**" in pattern or "*" in pattern or "?" in pattern:
        return fnmatch.fnmatchcase(path, pattern)
    return path == pattern


@pytest.fixture(scope="module")
def rules():
    return _parse_codeowners()


def test_all_rules_have_owner(rules):
    for pattern, owners in rules:
        assert owners, f"CODEOWNERS rule '{pattern}' has no owners"


@pytest.mark.parametrize("guarded_path", GUARDED_PATHS)
def test_guarded_path_has_security_owner(guarded_path, rules):
    matched = [
        (pat, owners)
        for pat, owners in rules
        if _matches(pat, guarded_path) and owners & SECURITY_OWNERS
    ]
    assert matched, (
        f"'{guarded_path}' is not covered by any CODEOWNERS rule "
        f"with {SECURITY_OWNERS}"
    )
