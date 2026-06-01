"""
Asserts that all PR5.5 security documentation files are present and well-formed.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_SECURITY = REPO_ROOT / "docs" / "security"

STRIDE_DOCS = [
    "stride-coordinator.md",
    "stride-mitm-headless.md",
    "stride-credential-vault.md",
    "stride-scrubber.md",
    "stride-network-isolation.md",
]


def test_threat_model_v2_present():
    path = DOCS_SECURITY / "threat-model-v2.0.md"
    assert path.exists(), f"Missing: {path}"
    assert path.stat().st_size > 1000, f"File too small: {path}"


def test_ga_readiness_checklist_present():
    path = DOCS_SECURITY / "ga-readiness-checklist.md"
    assert path.exists(), f"Missing: {path}"
    assert path.stat().st_size > 1000, f"File too small: {path}"


def test_five_stride_docs_present():
    for filename in STRIDE_DOCS:
        path = DOCS_SECURITY / filename
        assert path.exists(), f"Missing STRIDE doc: {path}"
        assert path.stat().st_size > 500, f"STRIDE doc too small: {path}"


def test_threat_model_lists_seven_surfaces():
    path = DOCS_SECURITY / "threat-model-v2.0.md"
    content = path.read_text(encoding="utf-8")
    for i in range(1, 8):
        assert f"Surface {i}" in content, f"threat-model-v2.0.md missing 'Surface {i}'"


def test_ga_checklist_has_all_eight_hard_gates():
    path = DOCS_SECURITY / "ga-readiness-checklist.md"
    content = path.read_text(encoding="utf-8")
    hard_gates_section_match = re.search(
        r"## Hard Gates.*?(?=^##|\Z)", content, re.MULTILINE | re.DOTALL
    )
    assert hard_gates_section_match, "ga-readiness-checklist.md missing '## Hard Gates' section"
    hard_gates_section = hard_gates_section_match.group(0)
    unchecked_items = re.findall(r"- \[ \]", hard_gates_section)
    assert len(unchecked_items) >= 8, (
        f"Expected >= 8 hard gate items, found {len(unchecked_items)}"
    )


def test_threat_model_has_signoff_table():
    path = DOCS_SECURITY / "threat-model-v2.0.md"
    content = path.read_text(encoding="utf-8")
    assert "Surface | Reviewer" in content, (
        "threat-model-v2.0.md missing sign-off table header 'Surface | Reviewer'"
    )


def test_stride_docs_mention_residual_risk():
    for filename in STRIDE_DOCS:
        path = DOCS_SECURITY / filename
        content = path.read_text(encoding="utf-8")
        assert "Residual risk" in content or "Residual Risk" in content, (
            f"{filename} does not mention 'Residual risk'"
        )
