"""W0/PR0.1 AST invariant — ``ALLOWED_TOOLS`` may only be assigned in one
canonical module.

Principle 4 of the consensus plan: one whitelist, one location. This
extends the existing ``test_kali_allowlist_single_source.py`` invariant
across the full ``backend/app/`` + ``backend/tests/fixtures/`` tree (the
older test only checked ``app/agents/``).
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
BACKEND_APP = BACKEND / "app"
TESTS_FIXTURES = BACKEND / "tests" / "fixtures"

ALLOWED_DEFINITION = (BACKEND_APP / "safety" / "kali_allowlist.py").resolve()


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in (BACKEND_APP, TESTS_FIXTURES):
        if not root.exists():
            continue
        files.extend(
            p for p in root.rglob("*.py")
            if "__pycache__" not in p.parts
        )
    return files


def _has_module_level_allowed_tools(tree: ast.AST) -> bool:
    body = tree.body if isinstance(tree, ast.Module) else []
    for node in body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "ALLOWED_TOOLS":
                    return True
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "ALLOWED_TOOLS":
                return True
    return False


def test_allowed_tools_defined_only_in_kali_allowlist():
    offenders: list[str] = []
    for p in _python_files():
        if p.resolve() == ALLOWED_DEFINITION:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError:
            continue
        if _has_module_level_allowed_tools(tree):
            offenders.append(str(p.relative_to(BACKEND)))
    assert not offenders, (
        "ALLOWED_TOOLS must only be defined in backend/app/safety/kali_allowlist.py. "
        f"Redefinitions found in: {offenders}"
    )


def test_canonical_definition_module_exists_and_defines_allowed_tools():
    assert ALLOWED_DEFINITION.exists(), "canonical module missing"
    tree = ast.parse(ALLOWED_DEFINITION.read_text(encoding="utf-8"))
    assert _has_module_level_allowed_tools(tree), (
        "kali_allowlist.py must define ALLOWED_TOOLS at module level"
    )
