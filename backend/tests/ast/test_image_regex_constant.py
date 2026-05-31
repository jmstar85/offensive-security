"""W0/PR0.1 AST invariant — pin the ``IMAGE_REGEX`` constant in
``backend/app/infra/socket_proxy_filter.py``.

A future PR that adds a sidecar image namespace (mitmproxy / headless /
interactsh in W3) must also update this regex AND the test below. This
guard prevents an unauthorised expansion of the dockerd attack surface
from sneaking in via a one-line constant change.
"""
from __future__ import annotations

import ast
from pathlib import Path

FILTER = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "infra"
    / "socket_proxy_filter.py"
)

# v1.1 pin: only osa-kali images are creatable through the proxy.
EXPECTED_REGEX_LITERAL = r"^osa-kali(?:[:@].+)?$"


def _find_image_regex_compile_arg(tree: ast.AST) -> str | None:
    body = tree.body if isinstance(tree, ast.Module) else []
    for node in body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "IMAGE_REGEX" for t in node.targets
        ):
            continue
        # IMAGE_REGEX = re.compile(<str literal>)
        if isinstance(node.value, ast.Call) and node.value.args:
            arg = node.value.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return arg.value
    return None


def test_image_regex_pinned_to_osa_kali_only():
    assert FILTER.exists(), f"missing socket_proxy_filter at {FILTER}"
    tree = ast.parse(FILTER.read_text(encoding="utf-8"))
    actual = _find_image_regex_compile_arg(tree)
    assert actual is not None, (
        "IMAGE_REGEX = re.compile(...) assignment not found in socket_proxy_filter.py"
    )
    assert actual == EXPECTED_REGEX_LITERAL, (
        f"IMAGE_REGEX literal changed.\n"
        f"  expected: {EXPECTED_REGEX_LITERAL!r}\n"
        f"  actual:   {actual!r}\n"
        f"If you are adding a sidecar namespace (W3) update BOTH the constant "
        f"AND this test under @security-reviewer CODEOWNERS."
    )
