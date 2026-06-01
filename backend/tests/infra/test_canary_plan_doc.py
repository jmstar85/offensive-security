"""Doc-coverage tests for the flag-tuple canary rollout plan — W5/PR5.4."""
import pathlib

DOC_PATH = pathlib.Path(__file__).parents[3] / "docs" / "rollout" / "flag-tuple-canary-plan.md"


def _doc_text() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_canary_plan_doc_exists():
    assert DOC_PATH.exists(), f"Expected rollout doc at {DOC_PATH}"


def test_canary_plan_references_four_tuples():
    text = _doc_text()
    for t in ("T1", "T2", "T3", "T4"):
        assert t in text, f"Tuple {t} not found in canary plan doc"


def test_canary_plan_specifies_sla():
    text = _doc_text()
    assert "10 minute" in text or "≤ 10" in text, (
        "Canary plan doc must mention '10 minute' or '≤ 10' SLA"
    )


def test_canary_plan_has_reverse_path():
    text = _doc_text()
    assert "T4 → T3" in text or "T4→T3" in text, (
        "Canary plan doc must describe the reverse rollback path (T4 → T3 ...)"
    )


def test_canary_plan_has_decision_matrix():
    text = _doc_text()
    for keyword in ("Promote", "Hold", "Rollback"):
        assert keyword in text, f"Decision matrix keyword '{keyword}' not found in canary plan doc"
