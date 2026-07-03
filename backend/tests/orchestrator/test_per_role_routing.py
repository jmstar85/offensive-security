"""PR6 — per-role routing via the explicit ``client_factory`` (A1b, Finding 1,
Blocking 2/3, Improvement 3, round-6 signature fix).

Covers, with heavy mocking (no real DB / network):
  * two-role same-session → Ollama (Pentester) + Anthropic (Generator) both spied;
  * Adviser routed correctly AS A SUB-ROLE through ``delegate_tool_call`` off the
    SHARED performer/factory (proves Finding 1 fixed — payload carries no routing
    inputs);
  * empty ``model_map`` + explicit provider = a REAL ``AnthropicProvider`` vs
    opus-4-8 (labelled NEW behavior, Principle 9);
  * bound-lane missing-credential RAISES ``CredentialNotFound`` per consuming role
    (fail-closed, never smoke — Principle 7 / AC#10), both via the factory and via
    the ``if client is None`` bound-live guard;
  * reporter triggers NO client resolution (accept-and-ignore, no phantom touch);
  * Blocking 2 — repeated invocations RE-RESOLVE (fresh ``route()``, no cached
    client);
  * Blocking 3 — the delegator chokepoint enforces factory presence with an
    explicit ``raise`` that survives ``python -O`` (asserts stripped);
  * round-6 positive — a full ``generator → pentester → reporter`` topological
    chain completes through the uniform ``reflector_wrap`` launch site with NO
    ``TypeError`` (non-consuming roles accept-and-ignore the kwarg).
"""
from __future__ import annotations

import inspect
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

# Register the Minimal 6 roles (import side-effect) before anything reads them.
import app.orchestrator.roles.seed  # noqa: F401
from app.orchestrator.llm.anthropic_provider import AnthropicProvider
from app.orchestrator.llm.credential_resolver import CredentialNotFound
from app.orchestrator.llm.router import LLMRouter
from app.orchestrator.ollama_client import OllamaClient
from app.orchestrator.performer import Performer
from app.orchestrator.roles.adviser import Adviser
from app.orchestrator.roles.generator import Generator
from app.orchestrator.roles.llm_provider import build_client_factory
from app.orchestrator.roles.pentester import Pentester
from app.orchestrator.roles.registry import get_role
from app.orchestrator.roles.reporter import Reporter
from app.orchestrator.runtime_delegator import delegate_tool_call

_BACKEND_DIR = Path(__file__).resolve().parents[2]

_DONE_ENVELOPE = '{"done": true, "summary": "ok"}'
_GEN_ENVELOPE = '{"ambiguity": 0.0, "blockers": [], "reasoning": "x", "draft_plan": {"steps": []}}'


def _resp(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, tokens_in=1, tokens_out=1, raw={})


def _unbound_performer() -> Performer:
    return Performer(AsyncMock(), uuid.uuid4())


def _bound_performer() -> Performer:
    p = Performer(AsyncMock(), uuid.uuid4())
    p.bind_live_execution(
        target={"ip_ranges": [], "domains": []},
        approval_flags={"approved_active_recon": True},
        whitelist_rules={},
        actor_id="actor-1",
    )
    return p


def _session(**kw):
    base = dict(model_map={}, llm_provider_pref=None, model_id=None)
    base.update(kw)
    return SimpleNamespace(**base)


# ── two-role same session: Ollama (Pentester) + Anthropic (Generator) ─────────


async def test_two_role_same_session_routes_ollama_and_anthropic():
    """AC#6: one session, ``model_map`` routes Pentester→Ollama and
    Generator→Anthropic; BOTH ``.send`` spies fire."""
    session = _session(
        model_map={"pentester": "qwen3-14b-96k:latest", "generator": "claude-opus-4-8"},
        model_id="claude-opus-4-8",
    )
    db, actor = AsyncMock(), uuid.uuid4()
    factory = build_client_factory(db, session, actor)
    performer = _unbound_performer()

    ollama_send = AsyncMock(return_value=_resp(_DONE_ENVELOPE))
    anthropic_send = AsyncMock(return_value=_resp(_GEN_ENVELOPE))
    with patch.object(OllamaClient, "send", ollama_send), patch.object(
        AnthropicProvider, "send", anthropic_send
    ), patch(
        "app.orchestrator.llm.credential_resolver.resolve_provider_credential",
        new=AsyncMock(return_value="sk-fake"),
    ):
        pen = await Pentester(tools_allowed=["nmap", "done"]).run(
            performer, {"objective": "scan the in-scope host"}, client_factory=factory
        )
        gen = await Generator().run(
            performer, {"user_content": "scan the host"}, client_factory=factory
        )

    assert pen.role_name == "pentester"
    assert gen.role_name == "generator"
    assert ollama_send.await_count == 1, "Pentester must route to OllamaClient"
    assert anthropic_send.await_count == 1, "Generator must route to AnthropicProvider"


# ── Adviser as a SUB-ROLE via delegate_tool_call (Finding 1) ──────────────────


async def test_adviser_routes_as_subrole_off_shared_performer():
    """AC#6 / Finding 1: Adviser invoked as a sub-role through
    ``delegate_tool_call`` resolves its client off the SHARED performer/factory,
    NOT from the operator-controlled ``payload`` (which carries no routing inputs
    and no ``model_client``)."""
    session = _session(model_map={"adviser": "claude-opus-4-8"})
    db, actor = AsyncMock(), uuid.uuid4()
    performer = _bound_performer()
    performer.state.context["role_client_inputs"] = {
        "db": db,
        "session": session,
        "actor_id": actor,
    }

    anthropic_send = AsyncMock(return_value=_resp("Switch from nmap to httpx."))
    with patch.object(AnthropicProvider, "send", anthropic_send), patch(
        "app.orchestrator.llm.credential_resolver.resolve_provider_credential",
        new=AsyncMock(return_value="sk-fake"),
    ):
        out = await delegate_tool_call(
            performer, "adviser", {"trigger_reason": "same_tool_called_5_times"},
            allow_role_invocation=True,
        )

    assert out["kind"] == "role"
    assert out["result"]["role_name"] == "adviser"
    # Proof of Finding-1 fix: routed to Anthropic despite the payload carrying no
    # role_client_inputs — the factory came from the shared performer context.
    assert anthropic_send.await_count == 1


# ── empty model_map + explicit provider = NEW behavior (Principle 9) ──────────


async def test_empty_model_map_explicit_provider_is_new_behavior_real_anthropic():
    """AC#22 (NEW behavior, NOT byte-identical): an empty ``model_map`` with an
    explicitly-chosen provider resolves each consuming role to a REAL
    ``AnthropicProvider`` against ``session.model_id`` — not ``None``→smoke."""
    session = _session(llm_provider_pref="anthropic", model_id="claude-opus-4-8")
    db, actor = AsyncMock(), uuid.uuid4()
    factory = build_client_factory(db, session, actor)
    performer = _unbound_performer()

    anthropic_send = AsyncMock(return_value=_resp(_GEN_ENVELOPE))
    with patch.object(AnthropicProvider, "send", anthropic_send), patch(
        "app.orchestrator.llm.credential_resolver.resolve_provider_credential",
        new=AsyncMock(return_value="sk-fake"),
    ):
        res = await Generator().run(
            performer, {"user_content": "scan"}, client_factory=factory
        )

    assert res.role_name == "generator"
    assert anthropic_send.await_count == 1  # real client, not a smoke envelope


# ── fail-closed on the bound live lane (Principle 7 / AC#10) ──────────────────


@pytest.mark.parametrize(
    "role_factory, ctx",
    [
        (lambda: Pentester(), {"objective": "x"}),
        (lambda: Generator(), {"user_content": "x"}),
        (lambda: Adviser(), {"trigger_reason": "loop_detected"}),
    ],
)
async def test_bound_lane_missing_cred_raises_per_consuming_role(role_factory, ctx):
    """A missing credential on the bound live lane RAISES ``CredentialNotFound``
    (propagated by the factory) — never degrades to a smoke fixture."""
    session = _session(llm_provider_pref="anthropic", model_id="claude-opus-4-8")
    db, actor = AsyncMock(), uuid.uuid4()
    factory = build_client_factory(db, session, actor)
    performer = _bound_performer()

    with patch(
        "app.orchestrator.llm.credential_resolver.resolve_provider_credential",
        new=AsyncMock(side_effect=CredentialNotFound("no cred")),
    ):
        with pytest.raises(CredentialNotFound):
            await role_factory().run(performer, ctx, client_factory=factory)


async def test_bound_lane_none_client_guard_raises_without_factory():
    """The explicit ``if client is None`` guard also fails closed on the bound
    live lane when NO factory is injected and the legacy path resolves ``None``
    (anthropic-without-injection) — the smoke branch is unreachable here."""
    performer = _bound_performer()
    with patch(
        "app.orchestrator.roles.llm_provider._provider", return_value="anthropic"
    ):
        with pytest.raises(CredentialNotFound):
            await Pentester().run(performer, {}, client_factory=None)


async def test_unbound_lane_none_client_still_smokes():
    """Additive: on an UNBOUND/demo context a ``None`` client still returns the
    smoke fixture unchanged (the fail-closed guard does not fire)."""
    performer = _unbound_performer()
    with patch(
        "app.orchestrator.roles.llm_provider._provider", return_value="anthropic"
    ):
        res = await Pentester().run(performer, {}, client_factory=None)
    assert res.tool_calls == 1
    assert "nmap" in res.messages[0]["content"]


# ── reporter triggers no client resolution (no phantom touch) ─────────────────


async def test_reporter_triggers_no_client_resolution():
    """AC#6: the non-consuming Reporter accepts ``client_factory`` but never calls
    it — no phantom credential resolution / ``last_used_at`` bump."""
    performer = _bound_performer()
    factory = AsyncMock()  # spy — must never be awaited
    res = await Reporter().run(performer, {}, client_factory=factory)
    assert res.role_name == "reporter"
    factory.assert_not_awaited()


# ── Blocking 2: per-invocation re-resolution, no cached client ────────────────


async def test_repeated_invocations_reresolve_no_cached_client():
    """AC#6b: each ``client_factory(role)`` call issues a FRESH ``LLMRouter.route``
    — a mid-session revoke is honored on the next call; no session-lived cache."""
    session = _session(model_map={"pentester": "qwen3-14b-96k:latest"})
    db, actor = AsyncMock(), uuid.uuid4()
    factory = build_client_factory(db, session, actor)

    route_spy = AsyncMock(return_value=OllamaClient())
    with patch.object(LLMRouter, "route", route_spy):
        await factory("pentester")
        await factory("pentester")

    assert route_spy.await_count == 2  # fresh route() each call, not one cached client


# ── Blocking 3: delegator explicit raise, survives python -O ──────────────────


def test_delegator_uses_explicit_raise_not_assert():
    """AC#6c (static): the delegator's factory-presence guard is an explicit
    ``raise RuntimeError``, NOT an ``assert`` (which ``python -O`` strips)."""
    src = inspect.getsource(delegate_tool_call)
    assert "raise RuntimeError" in src
    assert "assert client_factory" not in src
    assert "assert role_client_inputs" not in src


def test_delegator_raise_survives_python_O():
    """AC#6c (runtime): under ``python -O`` (asserts stripped) a CONSUMING sub-role
    with no ``role_client_inputs`` still raises ``RuntimeError`` at the chokepoint."""
    script = textwrap.dedent(
        """
        import asyncio, sys, uuid
        from unittest.mock import AsyncMock
        import app.orchestrator.roles.seed  # noqa: F401  (register roles)
        from app.orchestrator.performer import Performer
        from app.orchestrator.runtime_delegator import delegate_tool_call

        async def main() -> int:
            p = Performer(AsyncMock(), uuid.uuid4())  # empty context: no role_client_inputs
            try:
                await delegate_tool_call(p, "adviser", {}, allow_role_invocation=True)
            except RuntimeError:
                print("RAISED")
                return 0
            print("NO_RAISE")
            return 1

        sys.exit(asyncio.run(main()))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-O", "-c", script],
        cwd=str(_BACKEND_DIR),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "RAISED" in proc.stdout


# ── round-6 positive: full topological chain, no TypeError ────────────────────


async def test_full_topological_chain_completes_through_launch_site():
    """AC#6d: ``generator → pentester → reporter`` runs to completion through the
    uniform ``reflector_wrap(role.run, …, client_factory=…)`` launch site with NO
    ``TypeError`` — the non-consuming Reporter accepts-and-ignores the forwarded
    kwarg (the round-6 blocking regression that halted every fresh-plan run)."""
    session = _session(llm_provider_pref="ollama")  # keyless — no credential lookup
    db, actor = AsyncMock(), uuid.uuid4()
    performer = Performer(db, uuid.uuid4())
    performer.state.context["role_client_inputs"] = {
        "db": db,
        "session": session,
        "actor_id": actor,
    }
    performer.register_role(get_role("generator")())
    performer.register_role(Pentester(tools_allowed=["nmap", "done", "ask", "search_in_memory"]))
    performer.register_role(get_role("reporter")())

    with patch.object(OllamaClient, "send", AsyncMock(return_value=_resp(_DONE_ENVELOPE))):
        results = await performer.run_session()

    assert [r.role_name for r in results] == ["generator", "pentester", "reporter"]
    assert all(r.error is None for r in results), [r.error for r in results]
