"""Guards `KALI_ALLOWED_CAPS == frozenset()` for v1.

Any future PR that needs a non-empty capability set MUST update both this
test and the runbook ADR step (per A5.5 of the consensus plan).
"""
from __future__ import annotations

from app.safety.kali_allowlist import ALLOWED_TOOLS, KALI_ALLOWED_CAPS


def test_kali_allowed_caps_is_empty_for_v1() -> None:
    assert KALI_ALLOWED_CAPS == frozenset(), (
        f"v1 must ship with empty KALI_ALLOWED_CAPS; got {KALI_ALLOWED_CAPS!r}. "
        "Any expansion requires an ADR + security-reviewer sign-off per A5.5."
    )


def test_each_allowed_tool_cap_add_is_subset_of_allowed_caps() -> None:
    for slug, entry in ALLOWED_TOOLS.items():
        cap_add = set(entry.get("cap_add", []))
        assert cap_add <= set(KALI_ALLOWED_CAPS), (
            f"Tool {slug!r} has cap_add={cap_add!r} which is not a subset of "
            f"KALI_ALLOWED_CAPS={set(KALI_ALLOWED_CAPS)!r}."
        )
