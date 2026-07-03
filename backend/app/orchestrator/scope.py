"""Shared session-start target-scope gate (PR7 / PM2-B).

``validate_session_target`` is the ONE pure callable both the Automation lane
(``OrchestratorService.run``) and the Assistant lane (``AssistantService.turn``)
run once, before the first tool dispatch, to reject an out-of-scope SESSION
target. It is a pure refactor of the whitelist check that lived inline in
``OrchestratorService.run`` (service.py) — same inputs, same
``WhitelistValidator.validate_target`` call, same ``(is_valid, violations)``
return — so Path A replay stays byte-identical.

The per-CALL scope brake (an out-of-scope host named in a tool ``config`` after a
container launches) is the runtime ``EgressMonitor`` on BOTH lanes — there is no
per-call pre-flight gate here (symmetry with Automation, Principle 4 / PM2-B).
"""
from __future__ import annotations

from app.safety.whitelist import WhitelistValidator


def validate_session_target(
    target: dict, whitelist_rules: dict
) -> tuple[bool, list[str]]:
    """Return ``(is_valid, violations)`` for *target* against *whitelist_rules*.

    Pure: constructs a ``WhitelistValidator`` from the rules and validates the
    session target. No audit, no DB, no side effects — the caller owns the
    fail/audit/publish reaction so behavior stays identical to the prior inline
    gate.
    """
    validator = WhitelistValidator(whitelist_rules)
    return validator.validate_target(target)
