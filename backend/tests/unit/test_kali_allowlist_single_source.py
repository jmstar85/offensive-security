"""AST guard — Kali tool allowlist must have a SINGLE source location.

Fails the build if either:
  (a) any module-level `ALLOWED_TOOLS = ...` assignment appears OUTSIDE
      `backend/app/safety/kali_allowlist.py`, or
  (b) any Kali tool binary path literal (`/usr/bin/gobuster`,
      `/usr/bin/sqlmap`, `/usr/bin/nikto`) appears outside that file.

Scope: backend/app/agents/**/*.py and backend/tests/fixtures/**/*.py (recursive).

Rationale: Principle 4 of the consensus plan — "One whitelist, one location."
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # backend/
AGENTS_TREE = BACKEND_ROOT / "app" / "agents"
FIXTURES_TREE = BACKEND_ROOT / "tests" / "fixtures"
ALLOWED_DEFINITION_FILE = (
    BACKEND_ROOT / "app" / "safety" / "kali_allowlist.py"
).resolve()

FORBIDDEN_BINARY_LITERALS = frozenset(
    {"/usr/bin/gobuster", "/usr/bin/sqlmap", "/usr/bin/nikto"}
)


def _python_files_under(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [p for p in root.rglob("*.py") if p.is_file()]


def _module_level_allowed_tools_assignment(tree: ast.AST) -> bool:
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "ALLOWED_TOOLS":
                    return True
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "ALLOWED_TOOLS":
                return True
    return False


def _forbidden_binary_literals(tree: ast.AST) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in FORBIDDEN_BINARY_LITERALS:
                hits.append(node.value)
    return hits


def test_no_allowed_tools_redefinition_outside_safety() -> None:
    offenders: list[str] = []
    for path in _python_files_under(AGENTS_TREE) + _python_files_under(FIXTURES_TREE):
        if path.resolve() == ALLOWED_DEFINITION_FILE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if _module_level_allowed_tools_assignment(tree):
            offenders.append(str(path))
    assert not offenders, (
        "ALLOWED_TOOLS must only be defined in backend/app/safety/kali_allowlist.py. "
        f"Redefinitions found in: {offenders}"
    )


def test_no_kali_binary_path_literals_outside_safety() -> None:
    offenders: list[tuple[str, str]] = []
    for path in _python_files_under(AGENTS_TREE) + _python_files_under(FIXTURES_TREE):
        if path.resolve() == ALLOWED_DEFINITION_FILE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for literal in _forbidden_binary_literals(tree):
            offenders.append((str(path), literal))
    assert not offenders, (
        "Kali binary path literals must only live in "
        "backend/app/safety/kali_allowlist.py via ALLOWED_TOOLS entries. "
        f"Literals found: {offenders}"
    )
