"""Executor topic-tagged publish regression test (v4.0 P4 gap-fill 3/3,
updated v1.1-#1 to cover the second `agent_failed` branch added when
shim_block was promoted to a specific SafetyViolation catch).

Verifies the five `event_bus.publish` call sites in `executor.py` route to
the correct UI panel topic per `.omc/research/pentagi-reference.md §4`:

| Source event                         | Topic       | UI panel       |
|--------------------------------------|-------------|----------------|
| `agent_started`                      | `tasks`     | Tasks tab      |
| adapter `event.log`                  | `terminal`  | Terminal tab   |
| adapter `event.status`               | `agents`    | Agents tab     |
| `agent_failed` (shim_block branch)   | `tasks`     | Tasks tab      |
| `agent_failed` (generic branch)      | `tasks`     | Tasks tab      |
| `agent_completed`                    | `tasks`     | Tasks tab      |

If a future refactor accidentally drops a topic kwarg, a panel will go dark
under flag-on operation — this test prevents that regression.
"""
from __future__ import annotations

from pathlib import Path

EXECUTOR = Path(__file__).resolve().parents[2] / "app" / "orchestrator" / "executor.py"


def _publish_sites() -> list[str]:
    """Return every `event_bus.publish(...)` call body (raw text) in executor.py."""
    text = EXECUTOR.read_text(encoding="utf-8")
    sites: list[str] = []
    cursor = 0
    while True:
        i = text.find("event_bus.publish(", cursor)
        if i < 0:
            break
        # Walk balanced parens to capture the entire call (handles multi-line).
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


def test_executor_has_seven_publish_sites():
    # 6 original + the per-step Agents-tab narration event (msgchain_updated,
    # topic="agents") added by _narrate_step.
    sites = _publish_sites()
    assert len(sites) == 7, (
        f"Expected 7 publish sites in executor.py; found {len(sites)}. "
        "If you added or removed one, update this regression test."
    )


def test_every_publish_carries_a_topic_kwarg():
    sites = _publish_sites()
    for i, body in enumerate(sites):
        assert "topic=" in body, (
            f"Publish site #{i + 1} in executor.py is missing a `topic=` "
            f"kwarg. Under flag-on operation this event will not reach any "
            f"per-panel subscriber. Body: {body[:120]!r}"
        )


def test_agent_lifecycle_events_route_to_tasks_topic():
    sites = _publish_sites()
    lifecycle = [
        b for b in sites
        if any(t in b for t in ('"agent_started"', '"agent_failed"', '"agent_completed"'))
    ]
    # v1.1-#1 added a second `agent_failed` site for the SafetyViolation
    # (shim_block) branch — both still route to the Tasks tab.
    assert len(lifecycle) == 4, "Expected 4 lifecycle publish sites (incl. 2 agent_failed)"
    for body in lifecycle:
        assert 'topic="tasks"' in body, (
            f"Lifecycle event must route to Tasks tab; got: {body[:160]!r}"
        )


def test_log_events_route_to_terminal_topic():
    sites = _publish_sites()
    # The inline-event publish branches on `event.event_type`. Verify the
    # source contains the "terminal" routing for log lines.
    text = EXECUTOR.read_text(encoding="utf-8")
    assert '"terminal" if event.event_type == "log" else "agents"' in text, (
        "executor.py must branch log→terminal, other→agents in the inner loop"
    )
