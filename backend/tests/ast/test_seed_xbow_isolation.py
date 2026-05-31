"""MF5 invariant enforcement: seed_xbow isolation + no-import-at-module-level."""
from __future__ import annotations

import ast
import importlib
import sys

import pytest

from app.orchestrator.roles.registry import ROLE_REGISTRY

_XBOW_SLUGS = {"session_management_agent", "discovery_agent", "attack_agent"}
_SEED_XBOW_MODULE = "app.orchestrator.roles.seed_xbow"

_BACKEND_ROOT = (
    __file__
    .replace("/tests/ast/test_seed_xbow_isolation.py", "")
    .replace("\\tests\\ast\\test_seed_xbow_isolation.py", "")
)


@pytest.fixture()
def clean_registry():
    snapshot = dict(ROLE_REGISTRY)
    yield
    ROLE_REGISTRY.clear()
    ROLE_REGISTRY.update(snapshot)


def test_seed_xbow_does_not_register_at_import(clean_registry):
    """Importing seed_xbow must NOT add xbow slugs to ROLE_REGISTRY."""
    before = set(ROLE_REGISTRY.keys())
    # Force re-evaluation even if module was cached
    if _SEED_XBOW_MODULE in sys.modules:
        del sys.modules[_SEED_XBOW_MODULE]
    importlib.import_module(_SEED_XBOW_MODULE)
    after = set(ROLE_REGISTRY.keys())
    newly_added = after - before
    assert _XBOW_SLUGS.isdisjoint(newly_added), (
        f"seed_xbow import caused xbow slug registration: {_XBOW_SLUGS & newly_added}"
    )


def test_seed_py_imports_unchanged():
    """AST-parse seed.py — must NOT import seed_xbow."""
    seed_path = f"{_BACKEND_ROOT}/app/orchestrator/roles/seed.py"
    with open(seed_path) as f:
        tree = ast.parse(f.read(), filename=seed_path)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = ""
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name
                    assert "seed_xbow" not in module, (
                        f"seed.py must not import seed_xbow (found: {module})"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "seed_xbow" not in module, (
                    f"seed.py must not import from seed_xbow (found: {module})"
                )


def test_seed_xbow_module_has_no_register_role_calls_at_top_level():
    """AST-parse seed_xbow.py — register_role must only appear inside _register_all."""
    seed_xbow_path = f"{_BACKEND_ROOT}/app/orchestrator/roles/seed_xbow.py"
    with open(seed_xbow_path) as f:
        tree = ast.parse(f.read(), filename=seed_xbow_path)

    # Collect all top-level call nodes (not inside any function)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Expr, ast.Assign, ast.AugAssign)):
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    func = child.func
                    name = ""
                    if isinstance(func, ast.Name):
                        name = func.id
                    elif isinstance(func, ast.Attribute):
                        name = func.attr
                    assert name != "register_role", (
                        "register_role must not be called at top-level in seed_xbow.py; "
                        "only inside _register_all()"
                    )


def test_main_py_lazy_register_call_is_flag_gated():
    """AST-parse main.py — lazy_register_if_enabled must reference osa_xbow_families_enabled."""
    main_path = f"{_BACKEND_ROOT}/app/main.py"
    with open(main_path) as f:
        source = f.read()
        tree = ast.parse(source, filename=main_path)

    dump = ast.dump(tree)
    assert "lazy_register_if_enabled" in dump, (
        "main.py must call lazy_register_if_enabled"
    )
    assert "osa_xbow_families_enabled" in source, (
        "main.py must reference osa_xbow_families_enabled when calling lazy_register_if_enabled"
    )
