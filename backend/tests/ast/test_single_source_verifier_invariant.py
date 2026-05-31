"""W0/PR0.1 AST invariant — ``ALLOWED_TOOLS`` may only be assigned in
canonical allowlist modules; DENY_FLAGS and PATH_DENY_PATTERNS only in
kali_allowlist; SafetyViolation re-exported consistently.

Principle 4 of the consensus plan: one whitelist, one location. This
extends the existing ``test_kali_allowlist_single_source.py`` invariant
across the full ``backend/app/`` + ``backend/tests/fixtures/`` tree (the
older test only checked ``app/agents/``).

PR3.5 extends this to cover mitm_allowlist and headless_allowlist.
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
BACKEND_APP = BACKEND / "app"
TESTS_FIXTURES = BACKEND / "tests" / "fixtures"

KALI_ALLOWLIST = (BACKEND_APP / "safety" / "kali_allowlist.py").resolve()
MITM_ALLOWLIST = (BACKEND_APP / "safety" / "mitm_allowlist.py").resolve()
HEADLESS_ALLOWLIST = (BACKEND_APP / "safety" / "headless_allowlist.py").resolve()

# ALLOWED_TOOLS may only be defined in these three modules.
ALLOWED_TOOLS_CANONICAL: frozenset[Path] = frozenset({
    KALI_ALLOWLIST,
    MITM_ALLOWLIST,
    HEADLESS_ALLOWLIST,
})

# DENY_FLAGS and PATH_DENY_PATTERNS may only be defined in kali_allowlist.
ALLOWED_DEFINITION = KALI_ALLOWLIST


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


def _module_level_assignments(tree: ast.AST) -> set[str]:
    """Return all names assigned at module level."""
    names: set[str] = set()
    body = tree.body if isinstance(tree, ast.Module) else []
    for node in body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _has_module_level_allowed_tools(tree: ast.AST) -> bool:
    return "ALLOWED_TOOLS" in _module_level_assignments(tree)


def test_allowed_tools_defined_only_in_canonical_allowlists():
    """ALLOWED_TOOLS must only be defined in the three allowlist modules."""
    offenders: list[str] = []
    for p in _python_files():
        if p.resolve() in ALLOWED_TOOLS_CANONICAL:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError:
            continue
        if _has_module_level_allowed_tools(tree):
            offenders.append(str(p.relative_to(BACKEND)))
    assert not offenders, (
        "ALLOWED_TOOLS must only be defined in kali_allowlist.py, "
        "mitm_allowlist.py, or headless_allowlist.py. "
        f"Redefinitions found in: {offenders}"
    )


def test_deny_flags_and_path_deny_patterns_only_in_kali_allowlist():
    """DENY_FLAGS and PATH_DENY_PATTERNS must only be defined in kali_allowlist."""
    deny_offenders: list[str] = []
    path_offenders: list[str] = []
    for p in _python_files():
        if p.resolve() == KALI_ALLOWLIST:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError:
            continue
        names = _module_level_assignments(tree)
        if "DENY_FLAGS" in names:
            deny_offenders.append(str(p.relative_to(BACKEND)))
        if "PATH_DENY_PATTERNS" in names:
            path_offenders.append(str(p.relative_to(BACKEND)))
    assert not deny_offenders, (
        "DENY_FLAGS must only be defined in kali_allowlist.py. "
        f"Redefinitions found in: {deny_offenders}"
    )
    assert not path_offenders, (
        "PATH_DENY_PATTERNS must only be defined in kali_allowlist.py. "
        f"Redefinitions found in: {path_offenders}"
    )


def test_mitm_and_headless_reexport_safety_violation():
    """mitm_allowlist and headless_allowlist must re-export SafetyViolation from kali_allowlist."""
    for module_path in (MITM_ALLOWLIST, HEADLESS_ALLOWLIST):
        assert module_path.exists(), f"{module_path.name} does not exist"
        source = module_path.read_text(encoding="utf-8")
        assert "from app.safety.kali_allowlist import" in source, (
            f"{module_path.name} must re-export from kali_allowlist"
        )
        assert "SafetyViolation" in source, (
            f"{module_path.name} must re-export SafetyViolation"
        )


def test_allowed_tools_defined_only_in_kali_allowlist():
    """Legacy single-source test kept for backward compat — delegates to broader test."""
    offenders: list[str] = []
    for p in _python_files():
        if p.resolve() in ALLOWED_TOOLS_CANONICAL:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError:
            continue
        if _has_module_level_allowed_tools(tree):
            offenders.append(str(p.relative_to(BACKEND)))
    assert not offenders, (
        "ALLOWED_TOOLS must only be defined in the canonical allowlist modules. "
        f"Redefinitions found in: {offenders}"
    )


def test_canonical_definition_module_exists_and_defines_allowed_tools():
    assert KALI_ALLOWLIST.exists(), "kali_allowlist.py missing"
    tree = ast.parse(KALI_ALLOWLIST.read_text(encoding="utf-8"))
    assert _has_module_level_allowed_tools(tree), (
        "kali_allowlist.py must define ALLOWED_TOOLS at module level"
    )
    for module_path in (MITM_ALLOWLIST, HEADLESS_ALLOWLIST):
        assert module_path.exists(), f"{module_path.name} missing"
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        assert _has_module_level_allowed_tools(tree), (
            f"{module_path.name} must define ALLOWED_TOOLS at module level"
        )
