"""PR5.3 — asserts that the runbook set is complete and non-stub."""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNBOOKS_DIR = REPO_ROOT / "docs" / "runbooks"

EXPECTED_SLUGS = [
    "cost-budget-exceeded",
    "coordinator-iteration-cap",
    "mitm-shim-block",
    "headless-shim-block",
    "oob-callback-received",
    "credential-revoked",
    "conversation-scrubbed",
    "conversation-scrub-circuit-open",
    "conversation-canary-leak",
    "raw-conversation-subscribed",
    "infra-network-membership-violation",
    "coordinator-skipped-for-replay-lane",
    "unsupported-flag-topology",
    "admin-enrich-understanding",
]


def _runbook_path(slug: str) -> Path:
    return RUNBOOKS_DIR / f"{slug}.md"


def test_one_runbook_per_audit_event() -> None:
    for slug in EXPECTED_SLUGS:
        path = _runbook_path(slug)
        assert path.exists(), f"Missing runbook: {path}"
        content = path.read_text()
        severity_match = re.search(r"\*\*Severity:\*\*\s+\S+", content)
        assert severity_match, f"{slug}: no non-empty Severity line found"
        triage_match = re.search(r"##\s+Triage steps", content)
        assert triage_match, f"{slug}: no 'Triage steps' section found"


def test_flag_tuple_table_exists() -> None:
    table_path = RUNBOOKS_DIR / "flag-tuple-replacement-table.md"
    assert table_path.exists(), f"Missing flag tuple table: {table_path}"
    content = table_path.read_text()
    assert ("T1→T2" in content) or ("T1 → T2" in content), (
        "flag-tuple-replacement-table.md must describe the T1→T2 transition"
    )


def test_no_runbook_is_a_stub() -> None:
    for slug in EXPECTED_SLUGS:
        path = _runbook_path(slug)
        assert path.exists(), f"Missing runbook: {path}"
        size = path.stat().st_size
        assert size > 500, f"{slug}: file size {size} bytes is below 500-byte stub threshold"


def test_runbooks_cross_link() -> None:
    cross_linked = 0
    for slug in EXPECTED_SLUGS:
        path = _runbook_path(slug)
        if not path.exists():
            continue
        content = path.read_text()
        if re.search(r"\[\[[a-z][a-z0-9-]+\]\]", content):
            cross_linked += 1
    assert cross_linked >= 3, (
        f"Only {cross_linked} runbooks contain [[name]] cross-links; expected at least 3"
    )
