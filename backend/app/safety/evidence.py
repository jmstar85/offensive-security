"""Finding evidence tagging (PR8 / C5).

Attaches a lightweight, deterministic provenance tag to each finding describing
WHAT supports it (source tool + the most proof-like field). This is evidence
*provenance*, NOT an exploit-success verdict — the dedicated validator agent that
re-proves exploitation is a documented milestone-2 item (see
``app/orchestrator/oob_correlation.py``) and is intentionally not built here.
"""
from __future__ import annotations

# Most-proof-like finding fields, in priority order.
_PROOF_KEYS = (
    "oob_callback",
    "correlation_id",
    "cve",
    "module",
    "match",
    "url",
    "status",
    "port",
    "service",
)


def tag_finding_evidence(finding: dict) -> dict:
    """Return ``finding`` with an ``evidence_tag`` + ``evidence_source`` (idempotent)."""
    if not isinstance(finding, dict):
        return finding
    if finding.get("evidence_tag"):
        return finding
    source = finding.get("agent_type") or finding.get("source") or "unknown"
    ftype = finding.get("type", "finding")
    proof = next(
        (f"{k}={finding[k]}" for k in _PROOF_KEYS if finding.get(k) is not None),
        None,
    )
    tag = f"{source}:{ftype}" + (f"|{proof}" if proof else "")
    return {**finding, "evidence_tag": tag, "evidence_source": source}


def tag_all(findings: list[dict]) -> list[dict]:
    """Evidence-tag every finding in a list."""
    return [tag_finding_evidence(f) for f in findings]
