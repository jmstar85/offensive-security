"""Build-time AST guard for the PR6 per-role ``client_factory`` contract (A1b).

Two invariants, enforced structurally so a future edit that reopens the
Finding-1 routing hole or the round-6 signature gap fails at build time:

(a) READ-SITE — every CONSUMING role (``pentester``/``generator``/``adviser``)
    resolves its LLM client via the INJECTED ``client_factory`` parameter and
    NEVER reconstructs routing inputs from the ``context``/``payload`` parameter
    (``context["role_client_inputs"]``). That reconstruction is exactly the
    Option-A1 hole A1b fixes: a sub-role invoked with ``context=payload`` has no
    ``role_client_inputs`` key, so reading it there silently falls back to a
    shared/None client. Non-consuming roles (e.g. ``reporter``) must NOT call the
    factory at all (no phantom credential touch).

(b) ACCEPT-SIGNATURE — because the uniform launch site
    (``reflector_wrap(role.run, …, client_factory=…)``) forwards the kwarg to
    EVERY role, ``base.Role.run`` and EVERY ``ROLE_REGISTRY`` role's ``run`` must
    ACCEPT ``client_factory``, and the abstract ``base.Role.run`` must carry the
    ``=None`` default so a future role subclassing an unfixed parent still fails
    closed at build time. Otherwise ``reporter``/``reflector`` raise ``TypeError``
    at the tail of every fresh-plan run — the round-6 blocking regression.

The legacy ``resolve_role_client(context.get("model_client"))`` fallback is an
INTENTIONAL, documented additive path reached ONLY when ``client_factory`` is
absent (never on the bound live lane, where the factory is always injected), so
it is not treated as a violation — the load-bearing safety property is (i) the
factory IS used and (ii) ``role_client_inputs`` is never read from the payload.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

# Populate ROLE_REGISTRY with the Minimal 6 (import side-effect) and the
# flag-gated XBOW families so the accept-signature invariant covers every role
# the launch site can forward the kwarg to.
import app.orchestrator.roles.seed  # noqa: F401  (registers Minimal 6)
from app.orchestrator.roles.base import Role
from app.orchestrator.roles.registry import ROLE_REGISTRY, lazy_register_if_enabled

lazy_register_if_enabled(True)  # registers seed_xbow families (idempotent)

CONSUMING_ROLES: frozenset[str] = frozenset({"pentester", "generator", "adviser"})


def _run_funcdef(cls: type) -> ast.AsyncFunctionDef | ast.FunctionDef:
    """Parse the class's ``run`` method into an AST FunctionDef node."""
    src = textwrap.dedent(inspect.getsource(cls.run))
    node = ast.parse(src).body[0]
    assert isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    return node


def _param_names(fn: ast.AsyncFunctionDef | ast.FunctionDef) -> list[str]:
    a = fn.args
    return [p.arg for p in (a.posonlyargs + a.args + a.kwonlyargs)]


def _client_factory_default_is_none(fn: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    a = fn.args
    posargs = a.posonlyargs + a.args
    # positional args with defaults align to the tail of posargs
    for arg, default in zip(posargs[len(posargs) - len(a.defaults):], a.defaults):
        if arg.arg == "client_factory":
            return isinstance(default, ast.Constant) and default.value is None
    for arg, default in zip(a.kwonlyargs, a.kw_defaults):
        if arg.arg == "client_factory":
            return (
                default is not None
                and isinstance(default, ast.Constant)
                and default.value is None
            )
    return False


def _calls_client_factory(fn: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "client_factory"
        for n in ast.walk(fn)
    )


def _reads_role_client_inputs_from_context(
    fn: ast.AsyncFunctionDef | ast.FunctionDef,
) -> bool:
    """True if the body reads ``role_client_inputs`` off the ``context``/``payload``
    parameter (either ``.get("role_client_inputs")`` or ``[...]`` subscript)."""
    params = {"context", "payload"}
    for node in ast.walk(fn):
        # context.get("role_client_inputs")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in params
        ):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and arg.value == "role_client_inputs":
                    return True
        # context["role_client_inputs"]
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id in params
        ):
            sl = node.slice
            if isinstance(sl, ast.Constant) and sl.value == "role_client_inputs":
                return True
    return False


# ── (b) accept-signature invariant ───────────────────────────────────────────


def test_base_role_run_carries_client_factory_none():
    """The abstract ``base.Role.run`` must ACCEPT ``client_factory`` with a
    ``=None`` default, so a future role subclassing without the fixed parent
    fails closed at build time (round-7 polish)."""
    fn = _run_funcdef(Role)
    assert "client_factory" in _param_names(fn), (
        "base.Role.run must accept a `client_factory` parameter."
    )
    assert _client_factory_default_is_none(fn), (
        "base.Role.run's `client_factory` must default to None."
    )


def test_every_registered_role_run_accepts_client_factory():
    """EVERY ROLE_REGISTRY role's ``run`` must ACCEPT ``client_factory`` — the
    uniform launch site forwards it to all of them, so a missing kwarg raises
    ``TypeError`` at runtime (round-6 blocking regression)."""
    offenders = [
        slug
        for slug, cls in ROLE_REGISTRY.items()
        if "client_factory" not in _param_names(_run_funcdef(cls))
    ]
    assert not offenders, (
        "these ROLE_REGISTRY roles' run() do not accept `client_factory` and will "
        f"raise TypeError at the uniform reflector_wrap launch site: {sorted(offenders)}"
    )


# ── (a) read-site invariant ──────────────────────────────────────────────────


def test_consuming_roles_use_injected_client_factory():
    """Each consuming role must actually CALL the injected ``client_factory``
    (i.e. resolve its client through the factory, not only accept the arg)."""
    for slug in sorted(CONSUMING_ROLES):
        assert slug in ROLE_REGISTRY, f"expected consuming role {slug!r} registered"
        fn = _run_funcdef(ROLE_REGISTRY[slug])
        assert "client_factory" in _param_names(fn), slug
        assert _calls_client_factory(fn), (
            f"consuming role {slug!r} must resolve its client via the injected "
            "client_factory(self.name), not only accept the argument."
        )


def test_consuming_roles_never_read_role_client_inputs_from_context():
    """Forbid the Option-A1 hole: a consuming role must NOT reconstruct routing
    inputs from the ``context``/``payload`` parameter (a sub-role's payload has no
    ``role_client_inputs`` key)."""
    offenders = [
        slug
        for slug in CONSUMING_ROLES
        if _reads_role_client_inputs_from_context(_run_funcdef(ROLE_REGISTRY[slug]))
    ]
    assert not offenders, (
        "these consuming roles read `role_client_inputs` from the context/payload "
        f"parameter instead of via the injected client_factory (Finding 1): {sorted(offenders)}"
    )


def test_non_consuming_roles_do_not_call_client_factory():
    """Roles that emit no model output (e.g. reporter/reflector/memorist) accept
    the kwarg but MUST NOT call the factory — no phantom credential touch."""
    non_consuming = set(ROLE_REGISTRY) - CONSUMING_ROLES
    offenders = [
        slug
        for slug in non_consuming
        if _calls_client_factory(_run_funcdef(ROLE_REGISTRY[slug]))
    ]
    assert not offenders, (
        "these non-consuming roles call client_factory (they must accept-and-ignore "
        f"it — no phantom credential resolution): {sorted(offenders)}"
    )
