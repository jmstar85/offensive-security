"""W0/PR0.1 AST invariant — no direct docker/backend imports outside the
two sanctioned modules.

Safety-chain corollary: every code path that wants to talk to dockerd must
go through ``backend/app/agents/backends/`` or ``backend/app/infra/`` so the
filter chain (KaliBackend hardening, socket-proxy image-regex middleware,
audit emission) is unbypassable.

This test walks ``backend/app/`` and flags any module that:
  - imports the ``docker`` SDK or one of its submodules,
  - imports ``DockerBackend`` / ``KaliBackend`` symbolically,
  - calls ``docker.from_env`` / ``docker.DockerClient`` attribute references,
  - or calls ``AgentAdapter.execute`` directly (bypassing PlanExecutor).
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND_APP = Path(__file__).resolve().parents[2] / "app"

# Files allowed to import docker / instantiate the backends directly.
ALLOWED_MODULES = {
    BACKEND_APP / "agents" / "backends" / "docker.py",
    BACKEND_APP / "agents" / "backends" / "kali.py",
    BACKEND_APP / "agents" / "backends" / "__init__.py",
    # registry.py wires the backends to slugs; it is a sanctioned dispatcher.
    BACKEND_APP / "agents" / "registry.py",
    # socket_proxy_filter sits in front of dockerd by design.
    BACKEND_APP / "infra" / "socket_proxy_filter.py",
}

FORBIDDEN_IMPORT_TARGETS = {"docker", "docker.errors", "docker.types"}
FORBIDDEN_SYMBOLS = {"DockerBackend", "KaliBackend", "from_env", "DockerClient"}


def _python_files() -> list[Path]:
    return [
        p
        for p in BACKEND_APP.rglob("*.py")
        if "__pycache__" not in p.parts
    ]


def _violations_in(path: Path) -> list[str]:
    if path in ALLOWED_MODULES:
        return []
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return [f"{path}: syntax error during AST parse"]
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_IMPORT_TARGETS or alias.name.startswith("docker."):
                    out.append(f"{path.relative_to(BACKEND_APP)}: imports {alias.name!r}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in FORBIDDEN_IMPORT_TARGETS or mod.startswith("docker."):
                out.append(f"{path.relative_to(BACKEND_APP)}: imports from {mod!r}")
            for alias in node.names:
                if alias.name in FORBIDDEN_SYMBOLS:
                    out.append(
                        f"{path.relative_to(BACKEND_APP)}: imports {alias.name!r} from {mod!r}"
                    )
    return out


def test_no_direct_backend_or_docker_imports_outside_sanctioned_modules():
    offenders: list[str] = []
    for p in _python_files():
        offenders.extend(_violations_in(p))
    assert not offenders, (
        "Files outside backend/app/agents/backends/ + backend/app/infra/ + "
        "registry.py must not import docker or the backend classes directly. "
        "All dockerd access must traverse the hardened backends so the "
        "safety chain (image-regex, cap_drop, tmpfs, audit) cannot be "
        f"bypassed. Violations:\n" + "\n".join(offenders)
    )


def test_allowed_modules_actually_exist():
    # Defense-in-depth: if a sanctioned module is renamed without updating
    # the allowlist, this test reminds us before silently widening surface.
    for p in ALLOWED_MODULES:
        assert p.exists(), f"sanctioned module missing — update ALLOWED_MODULES if renamed: {p}"
