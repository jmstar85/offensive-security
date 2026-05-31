"""W0/PR0.1 AST invariant (SF7) — count and cap the namespace count inside
``IMAGE_REGEX``.

Companion to ``test_image_regex_constant``: that test pins the literal
exactly; this one pins the alternation cardinality. The two are
deliberately overlapping — one is a tighter contract, the other is a
weaker guard that survives across cosmetic edits while still catching
namespace inflation.

v1.1 baseline: 1 namespace (osa-kali). Sidecars in W3 bring this to 4
(osa-kali / osa-mitmproxy / osa-headless-browser / osa-interactsh); at
that point this test gets bumped under @security-reviewer review.
"""
from __future__ import annotations

import ast
import re as _re
from pathlib import Path

FILTER = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "infra"
    / "socket_proxy_filter.py"
)

EXPECTED_NAMESPACE_COUNT = 4
EXPECTED_NAMESPACES = {
    "osa-kali", "osa-mitmproxy", "osa-headless-browser", "osa-interactsh",
}


def _image_regex_literal() -> str | None:
    if not FILTER.exists():
        return None
    tree = ast.parse(FILTER.read_text(encoding="utf-8"))
    body = tree.body if isinstance(tree, ast.Module) else []
    for node in body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "IMAGE_REGEX" for t in node.targets
        ):
            continue
        if isinstance(node.value, ast.Call) and node.value.args:
            arg = node.value.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return arg.value
    return None


def _extract_namespaces(literal: str) -> set[str]:
    """Pick out the leading-token alternation set from the anchored regex.

    Handles the v1.1 form ``^osa-kali(?:[:@].+)?$`` (one namespace) AND the
    forward-compatible W3 form ``^(osa-kali|osa-mitmproxy|...)(?:[:@].+)?$``.
    """
    m = _re.match(r"^\^(?P<group>[^()$]+|\([^)]+\))", literal)
    if m is None:
        return set()
    group = m.group("group").strip()
    if group.startswith("(") and group.endswith(")"):
        inner = group[1:-1]
        return {part.strip() for part in inner.split("|") if part.strip()}
    return {group}


def test_image_regex_namespace_count_pinned_to_v11_baseline():
    literal = _image_regex_literal()
    assert literal is not None, "IMAGE_REGEX literal not parseable"
    namespaces = _extract_namespaces(literal)
    assert len(namespaces) == EXPECTED_NAMESPACE_COUNT, (
        f"IMAGE_REGEX namespace count changed from {EXPECTED_NAMESPACE_COUNT} "
        f"to {len(namespaces)}. Sidecar expansion lands in W3 — both this test "
        f"AND .github/CODEOWNERS on the constant must be touched together."
    )
    assert namespaces == EXPECTED_NAMESPACES, (
        f"namespace identity changed: expected {EXPECTED_NAMESPACES}, got {namespaces}"
    )
