"""Structural guard: ``<adapter>.execute(...)`` may be called ONLY inside the
shared runtime helper ``safety_exec.py::execute_tool_through_safety_chain``.

Why a structural guard at all (Decision Driver #1, Scenario 1 DOMINANT): the live
runtime brakes (egress monitor, container-kill registration, rescope pause,
shim-audit) wrap the ``adapter.execute`` call. If a second code path calls
``adapter.execute`` directly, it bypasses those brakes. After PR2 there is exactly
ONE sanctioned call site — the runtime helper — so any other adapter-execute call
is a safety-control-plane bypass and must fail this test.

──────────────────────────────────────────────────────────────────────────────
Receiver-resolution heuristic (Residual Concern #2 — pinned + envelope documented)
──────────────────────────────────────────────────────────────────────────────
``get_adapter()`` returns a dynamically-typed object, so ``ast`` cannot resolve a
receiver's *type*. We therefore approximate "this ``.execute`` is an adapter
execute" with a two-tier rule, per function scope:

  PRIMARY (assignment-tracked receiver resolution):
    Within a single function body, track names bound from ``get_adapter(...)``:
        adapter = get_adapter(slug)        # binds 'adapter'
        x = get_adapter(slug)              # binds 'x'
    Then flag any ``<name>.execute(...)`` call whose ``<name>`` is in that bound
    set. This catches the real current call site (``executor.py:66`` —
    ``adapter = get_adapter(agent_type)`` at ``:61`` then ``adapter.execute`` at
    ``:66``) precisely.

  FALLBACK (textual proximity, only when assignment-tracking yields nothing in a
  function that nonetheless contains BOTH a ``get_adapter(`` token AND a
  ``.execute`` attribute call):
    Flag every ``.execute`` attribute call in that function. This covers cases
    where the adapter is not bound to a simple ``Name`` (e.g.
    ``get_adapter(slug).execute(...)`` inline, or rebinding through a container).

False-positive envelope (calls this MAY wrongly flag):
  * A ``.execute`` on an unrelated object (e.g. a SQLAlchemy ``Connection`` or a
    ``ThreadPoolExecutor``) that happens to live in the SAME function as a
    ``get_adapter(`` token would be flagged by the FALLBACK. Mitigation: the
    PRIMARY rule does not fire on these (their receiver is not bound from
    ``get_adapter``), so the fallback only triggers when the primary finds nothing
    AND both tokens coexist — rare, and a flagged false positive is a loud,
    fixable test failure (move the unrelated ``.execute`` out, or whitelist the
    module), never a silent bypass. ``db.execute(...)`` is the common case and is
    NOT named ``execute`` on an adapter-bound name, so PRIMARY ignores it; it is
    only ever at risk under FALLBACK, which is why FALLBACK is last-resort.

False-negative envelope (adapter-execute calls this MAY miss):
  * An adapter obtained through a chain ``ast`` cannot follow across functions
    (returned from a helper, stored on ``self``, pulled from a list). These are
    not caught structurally; they are caught at runtime by the spy harness
    (``test_safety_chain_full_envelope_spy.py``) and by code review. Documented,
    accepted, and the reason the runtime spy is a SEPARATE, complementary guard.

The guard is proven to detect the CURRENT call site today (``executor.py``), so the
heuristic is demonstrated on the real tree before PR2 flips the canonical-location
xfail (Residual Concern #2 gate).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND_APP = Path(__file__).resolve().parents[2] / "app"

# The ONLY module allowed to host an adapter-``.execute`` call after PR2.
SANCTIONED_HELPER_MODULE = BACKEND_APP / "orchestrator" / "safety_exec.py"
SANCTIONED_HELPER_FUNC = "execute_tool_through_safety_chain"


def _python_files() -> list[Path]:
    return [p for p in BACKEND_APP.rglob("*.py") if "__pycache__" not in p.parts]


def _adapter_execute_calls_in_function(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.Call]:
    """Return the ``ast.Call`` nodes in ``func`` that look like adapter-execute
    calls, per the pinned heuristic (PRIMARY assignment-tracking, FALLBACK
    textual-proximity)."""
    # ── PRIMARY: collect names bound from get_adapter(...) in this scope ──
    bound_from_get_adapter: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            callee = node.value.func
            callee_name = (
                callee.id if isinstance(callee, ast.Name)
                else callee.attr if isinstance(callee, ast.Attribute)
                else None
            )
            if callee_name == "get_adapter":
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        bound_from_get_adapter.add(tgt.id)

    # Collect every `.execute(...)` attribute call + whether the func mentions
    # get_adapter at all (for the fallback decision).
    execute_calls: list[ast.Call] = []
    inline_get_adapter_execute: list[ast.Call] = []
    func_mentions_get_adapter = bool(bound_from_get_adapter)

    for node in ast.walk(func):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "execute":
                execute_calls.append(node)
                recv = node.func.value
                # Inline: get_adapter(...).execute(...)
                if (
                    isinstance(recv, ast.Call)
                    and isinstance(recv.func, ast.Name)
                    and recv.func.id == "get_adapter"
                ):
                    inline_get_adapter_execute.append(node)
        # Detect a bare get_adapter( token anywhere in the function for fallback.
        if isinstance(node, ast.Call):
            callee = node.func
            name = (
                callee.id if isinstance(callee, ast.Name)
                else callee.attr if isinstance(callee, ast.Attribute)
                else None
            )
            if name == "get_adapter":
                func_mentions_get_adapter = True

    # PRIMARY hits: receiver is a Name bound from get_adapter, OR an inline
    # get_adapter(...).execute(...).
    primary: list[ast.Call] = list(inline_get_adapter_execute)
    for call in execute_calls:
        recv = call.func.value
        if isinstance(recv, ast.Name) and recv.id in bound_from_get_adapter:
            primary.append(call)

    if primary:
        return primary

    # FALLBACK: no primary hit, but the function both references get_adapter and
    # has at least one `.execute` call → flag all `.execute` calls.
    if func_mentions_get_adapter and execute_calls:
        return execute_calls

    return []


def _scan_tree() -> dict[Path, list[tuple[str, int]]]:
    """Map each file → list of (enclosing_function_name, lineno) adapter-execute
    call sites detected by the heuristic."""
    hits: dict[Path, list[tuple[str, int]]] = {}
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                calls = _adapter_execute_calls_in_function(node)
                if calls:
                    hits.setdefault(path, []).extend(
                        (node.name, c.lineno) for c in calls
                    )
    return hits


# ── Heuristic demonstration (Residual Concern #2 gate) ───────────────────────

def test_heuristic_detects_current_adapter_execute_call_site():
    """PROOF the heuristic works on the real tree TODAY: it must find at least one
    adapter-execute call, and that call must be in ``executor.py`` (the current
    home of ``adapter = get_adapter(...)`` / ``adapter.execute(...)``).

    This is the demonstration the plan requires before PR2 flips the
    canonical-location xfail below.
    """
    hits = _scan_tree()
    all_sites = [(p, fn, ln) for p, sites in hits.items() for (fn, ln) in sites]
    assert all_sites, (
        "heuristic found ZERO adapter-execute calls — it is broken; it must detect "
        "the current executor.py call site."
    )

    executor_py = BACKEND_APP / "orchestrator" / "executor.py"
    executor_sites = [s for s in all_sites if s[0] == executor_py]
    assert executor_sites, (
        "heuristic did not detect the known adapter.execute call in "
        f"executor.py; detected sites were: "
        f"{[(str(p.relative_to(BACKEND_APP)), fn, ln) for p, fn, ln in all_sites]}"
    )


# ── The invariant (xfail until PR2 introduces the helper) ────────────────────

@pytest.mark.xfail(
    reason="safety_exec.py::execute_tool_through_safety_chain helper lands in PR2; "
           "today the only adapter.execute call site is PlanExecutor.execute in "
           "executor.py, so the canonical-location invariant cannot hold yet. PR2 "
           "flips this to passing.",
    strict=False,
)
def test_adapter_execute_called_only_in_safety_helper():
    """Every adapter-execute call must live in
    ``safety_exec.py::execute_tool_through_safety_chain``.

    Pre-PR2 this fails (the call lives in ``executor.py``). PR2 moves the call into
    the helper and this flips green.
    """
    hits = _scan_tree()
    offenders: list[str] = []
    for path, sites in hits.items():
        for func_name, lineno in sites:
            in_sanctioned = (
                path == SANCTIONED_HELPER_MODULE
                and func_name == SANCTIONED_HELPER_FUNC
            )
            if not in_sanctioned:
                offenders.append(
                    f"{path.relative_to(BACKEND_APP)}:{lineno} (in {func_name}())"
                )
    assert not offenders, (
        "adapter.execute(...) may be called ONLY inside "
        f"{SANCTIONED_HELPER_MODULE.relative_to(BACKEND_APP)}::{SANCTIONED_HELPER_FUNC}. "
        "Every other call site bypasses the runtime safety envelope. Offenders:\n"
        + "\n".join(offenders)
    )
