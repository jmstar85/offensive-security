"""Tasks-tab lifecycle event-shape regression (Increment B).

The frontend TasksTab merges ``topic="tasks"`` events by overlaying
``...ev.step`` onto rows keyed by ``order``. For that overlay to update a
row's status, every lifecycle event (``agent_started`` / ``agent_completed`` /
``agent_failed``) MUST carry ``step={"order": <int>, "status": <str>}`` — a
dict, not the bare int the code originally emitted.

Both the deterministic lane (``executor.py::PlanExecutor.execute``) and the
autonomous lane (``performer.py::Performer._execute_step_through_helper``)
publish these events, so this test asserts the shape at BOTH source sites.
Parsing the source (rather than driving the full safety chain) keeps the test
line-shift-proof and free of Docker / DB scaffolding.
"""
from __future__ import annotations

from pathlib import Path

_APP = Path(__file__).resolve().parents[2] / "app" / "orchestrator"
EXECUTOR = _APP / "executor.py"
PERFORMER = _APP / "performer.py"

# Expected per-lifecycle-type status the `step` dict must carry.
_STATUS_BY_TYPE = {
    "agent_started": "running",
    "agent_completed": "completed",
    "agent_failed": "failed",
}


def _publish_sites(path: Path) -> list[str]:
    """Return every ``event_bus.publish(...)`` call body (raw text) in *path*."""
    text = path.read_text(encoding="utf-8")
    sites: list[str] = []
    cursor = 0
    while True:
        i = text.find("event_bus.publish(", cursor)
        if i < 0:
            break
        depth = 0
        j = i + len("event_bus.publish")
        while j < len(text):
            ch = text[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            j += 1
        sites.append(text[i:j])
        cursor = j
    return sites


def _lifecycle_bodies(path: Path) -> list[tuple[str, str]]:
    """Return (lifecycle_type, body) for every tasks-topic lifecycle publish."""
    out: list[tuple[str, str]] = []
    for body in _publish_sites(path):
        if 'topic="tasks"' not in body:
            continue
        for lc_type in _STATUS_BY_TYPE:
            if f'"{lc_type}"' in body:
                out.append((lc_type, body))
                break
    return out


def _assert_step_shape(path: Path, expected_counts: dict[str, int]) -> None:
    bodies = _lifecycle_bodies(path)
    seen: dict[str, int] = {t: 0 for t in _STATUS_BY_TYPE}
    for lc_type, body in bodies:
        seen[lc_type] += 1
        # Must carry a `step` DICT (frontend spreads `...ev.step` onto the row).
        assert '"step": {"order":' in body, (
            f"{path.name}: {lc_type} event must carry a step dict "
            f"(got body: {body[:200]!r})"
        )
        assert f'"status": "{_STATUS_BY_TYPE[lc_type]}"' in body, (
            f"{path.name}: {lc_type} step dict must carry "
            f'status="{_STATUS_BY_TYPE[lc_type]}" (got body: {body[:200]!r})'
        )
    assert seen == expected_counts, (
        f"{path.name}: expected lifecycle counts {expected_counts}, saw {seen}"
    )


def test_executor_lifecycle_events_carry_step_dict():  # noqa: D401
    # PlanExecutor.execute: 1 started, 1 completed, 4 failed
    # (shim_block + generic error + egress_violation + session_killed).
    _assert_step_shape(
        EXECUTOR,
        {"agent_started": 1, "agent_completed": 1, "agent_failed": 4},
    )


def test_performer_lifecycle_events_carry_step_dict():
    # _execute_step_through_helper: 1 started, 1 completed, 4 failed
    # (shim_block + generic error + egress_violation + session_killed).
    _assert_step_shape(
        PERFORMER,
        {"agent_started": 1, "agent_completed": 1, "agent_failed": 4},
    )
