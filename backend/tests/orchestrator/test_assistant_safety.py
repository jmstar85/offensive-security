"""PR7 — Assistant role-free service safety envelope (Option B1', Improvements 1/2).

Proves the Assistant reuses the ENTIRE existing safety envelope through the ONE
sanctioned dispatch chokepoint without adding a new reachable path (inbound OR
outbound) and without mutating Pentester's proven loop:

- shared ``validate_session_target`` (once) → filter_plan_steps →
  filter_by_tier_flags(session.approval_flags) → RiskFilter inside
  ``Performer._dispatch_tool`` via ``delegate_tool_call``, holding the
  ``_concurrency_guard`` lease (AC#11);
- recon auto-runs, exploit gated on ``approved_active_exploit`` (AC#11);
- OUTBOUND: ``{"tool":"pentester"|"adviser"|"memorist"}`` REFUSED by the
  ``delegate_tool_call`` default-deny — never launched as a sub-role (AC#12);
- disjoint namespaces ``list_agent_types() ∩ ROLE_REGISTRY == ∅`` (AC#12);
- single-sourced ``parse_tool_envelope`` shared with Pentester (AC#12b);
- INBOUND: ``{"tool":"assistant"}`` starts no loop (assistant ∉ ROLE_REGISTRY);
- fail-closed missing-cred RAISES, never smokes (AC#10);
- AST call-site: the Assistant module has no adapter.execute and imports no
  parallel dispatch symbol; it reaches ``_dispatch_tool`` via ``delegate_tool_call``.
"""
from __future__ import annotations

import inspect
import uuid
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import app.orchestrator.assistant_service as asvc
import app.safety.exploit_allowlist as eal
import app.safety.risk_filter as rf
from app.agents.base import AgentEvent
from app.agents.registry import list_agent_types
from app.orchestrator.assistant_service import AssistantService
from app.orchestrator.llm.credential_resolver import CredentialNotFound
from app.orchestrator.performer import _PerformerLease
from app.orchestrator.roles import seed as _seed  # noqa: F401  (populate ROLE_REGISTRY)
from app.orchestrator.roles.registry import ROLE_REGISTRY, lazy_register_if_enabled
from app.safety.egress_monitor import EgressMonitor

lazy_register_if_enabled(True)  # register seed_xbow families too (idempotent)


# ── fakes ────────────────────────────────────────────────────────────────────


class _FakeClient:
    """Returns canned ``.text`` responses (str) in order; falls back to a done
    envelope once drained (so a loop always terminates)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    async def send(self, model_id, messages, system, max_tokens=2048):  # noqa: ANN001
        self.calls.append(messages)
        item = self._responses.pop(0) if self._responses else '{"done": true, "summary": "done"}'
        return SimpleNamespace(text=item, tokens_in=1, tokens_out=1, raw={})


class _Result:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj

    def scalars(self):
        return self

    def first(self):
        return self._obj


class _FakeDB:
    """Returns a pre-seeded session for pentest_sessions selects and a target for
    targets selects; swallows writes (add/flush/commit) like the other unit fakes."""

    def __init__(self, session, target):
        self._session = session
        self._target = target
        self.added: list = []
        self.committed = False

    async def execute(self, stmt, *a, **k):  # noqa: ANN001
        t = str(stmt).lower()
        if "pentest_sessions" in t:
            return _Result(self._session)
        if "targets" in t:
            return _Result(self._target)
        return _Result(None)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.committed = True


def _fake_adapter(agent_type: str = "passive_recon", *, findings=None, executed=None):
    findings = findings or [{"type": "port"}]

    class _A:
        async def execute(self, target, config, holder=None) -> AsyncGenerator[AgentEvent, None]:
            if executed is not None:
                executed.append(agent_type)
            if holder is not None:
                holder.append(f"container-{agent_type}")
            yield AgentEvent("status", agent_type, "x", {"status": "running"})
            yield AgentEvent("status", agent_type, "x",
                             {"status": "completed", "result": {"findings": findings}})

    return _A()


def _session(*, mode="assistant", approval_flags=None, whitelist=None,
             domains=None, ip_ranges=None):
    sess = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        mode=mode,
        approval_flags=approval_flags or {},
        model_map={},
        llm_provider_pref="ollama",  # keyless — resolve never needs a credential
        model_id="qwen3-14b-96k:latest",
    )
    tgt = SimpleNamespace(
        ip_ranges=ip_ranges or [],
        domains=domains or [],
        whitelist_rules=whitelist if whitelist is not None else {},
    )
    return sess, tgt


def _user():
    return SimpleNamespace(id=uuid.uuid4())


# Envelopes.
_RECON = '{"tool": "passive_recon", "intent": "passive_dns_recon", "config": {}}'
_EXPLOIT = ('{"tool": "metasploit", "intent": "vulnerability_exploitation", '
            '"config": {"module": "auxiliary/scanner/portscan/tcp"}}')
_DONE = '{"done": true, "summary": "complete"}'


def _svc(session, target):
    return AssistantService(_FakeDB(session, target))


# ── recon auto-runs, exploit gated (AC#11) ────────────────────────────────────


@pytest.mark.asyncio
async def test_recon_turn_auto_runs():
    """A passive-tier recon tool auto-runs with NO approval flags."""
    session, target = _session()
    executed: list[str] = []
    client = _FakeClient([_RECON, _DONE])
    with patch.object(asvc, "resolve_session_role_client",
                      AsyncMock(return_value=client)), \
         patch("app.orchestrator.safety_exec.get_adapter",
               return_value=_fake_adapter("passive_recon", executed=executed)):
        result = await _svc(session, target).turn(session.id, "recon the host", _user())
    assert executed == ["passive_recon"]  # dispatched + executed through the chain
    assert result.content.startswith("[done]")


@pytest.mark.asyncio
async def test_exploit_turn_blocked_without_flag_runs_with_it():
    """An active_exploit tool is tier-gated: blocked without
    ``approved_active_exploit``, runs with it — same gate as Automation."""
    # Blocked.
    session, target = _session(approval_flags={})
    executed: list[str] = []
    with patch.object(asvc, "resolve_session_role_client",
                      AsyncMock(return_value=_FakeClient([_EXPLOIT, _DONE]))), \
         patch("app.orchestrator.safety_exec.get_adapter",
               return_value=_fake_adapter("metasploit", executed=executed)):
        await _svc(session, target).turn(session.id, "exploit", _user())
    assert executed == [], "exploit must NOT execute without approved_active_exploit"

    # Allowed.
    session2, target2 = _session(approval_flags={"approved_active_exploit": True})
    executed2: list[str] = []
    with patch.object(asvc, "resolve_session_role_client",
                      AsyncMock(return_value=_FakeClient([_EXPLOIT, _DONE]))), \
         patch("app.orchestrator.safety_exec.get_adapter",
               return_value=_fake_adapter("metasploit", executed=executed2)):
        await _svc(session2, target2).turn(session2.id, "exploit", _user())
    assert executed2 == ["metasploit"], "exploit must execute WITH the flag"


# ── ordered safety-chain spy + lease held (AC#11) ─────────────────────────────


@pytest.mark.asyncio
async def test_safety_chain_ordered_spy_and_lease_held():
    """shared validate_session_target (ONCE) → lease → filter_plan_steps →
    filter_by_tier_flags → RiskFilter inside _dispatch_tool via delegate_tool_call."""
    session, target = _session()
    calls: list[str] = []

    real_vst = asvc.validate_session_target
    def spy_vst(t, wl):  # noqa: ANN001
        calls.append("validate_session_target")
        return real_vst(t, wl)

    real_fps = eal.filter_plan_steps
    def spy_fps(steps):  # noqa: ANN001
        calls.append("filter_plan_steps")
        return real_fps(steps)

    real_fbtf = eal.filter_by_tier_flags
    def spy_fbtf(steps, flags):  # noqa: ANN001
        calls.append("filter_by_tier_flags")
        return real_fbtf(steps, flags)

    real_rf = rf.RiskFilter.filter_steps
    def spy_rf(self, steps):  # noqa: ANN001
        calls.append("risk_filter")
        return real_rf(self, steps)

    real_enter = _PerformerLease.__aenter__
    async def spy_enter(self):  # noqa: ANN001
        calls.append("lease_enter")
        return await real_enter(self)

    client = _FakeClient([_RECON, _DONE])
    with patch.object(asvc, "validate_session_target", spy_vst), \
         patch.object(eal, "filter_plan_steps", spy_fps), \
         patch.object(eal, "filter_by_tier_flags", spy_fbtf), \
         patch.object(rf.RiskFilter, "filter_steps", spy_rf), \
         patch.object(_PerformerLease, "__aenter__", spy_enter), \
         patch.object(asvc, "resolve_session_role_client",
                      AsyncMock(return_value=client)), \
         patch("app.orchestrator.safety_exec.get_adapter",
               return_value=_fake_adapter("passive_recon")):
        await _svc(session, target).turn(session.id, "recon", _user())

    assert calls.count("validate_session_target") == 1
    for stage in ("validate_session_target", "lease_enter", "filter_plan_steps",
                  "filter_by_tier_flags", "risk_filter"):
        assert stage in calls, f"{stage} never fired; order={calls}"
    assert calls.index("validate_session_target") < calls.index("lease_enter")
    assert calls.index("lease_enter") < calls.index("filter_plan_steps")
    assert calls.index("filter_plan_steps") < calls.index("filter_by_tier_flags")
    assert calls.index("filter_by_tier_flags") < calls.index("risk_filter")


# ── OUTBOUND containment: role slugs REFUSED, not launched (AC#12) ────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("role_slug", ["pentester", "adviser", "memorist"])
async def test_outbound_role_slug_refused_not_launched(role_slug):
    """An operator-emitted ROLE_REGISTRY slug is REFUSED by the delegate_tool_call
    default-deny (allow_role_invocation=False) — it is NOT run as a sub-role."""
    session, target = _session()
    executed: list[str] = []
    envelope = f'{{"tool": "{role_slug}", "intent": "x", "config": {{}}}}'
    client = _FakeClient([envelope, _DONE])
    with patch.object(asvc, "resolve_session_role_client",
                      AsyncMock(return_value=client)), \
         patch("app.orchestrator.safety_exec.get_adapter",
               return_value=_fake_adapter(role_slug, executed=executed)):
        svc = _svc(session, target)
        await svc.turn(session.id, "go", _user())

    # No adapter execution (roles are not adapters) AND the refusal is recorded.
    assert executed == []
    chain = [m for m in svc._db.added if getattr(m, "role_name", None) == "assistant"][0]
    tool_msgs = [m for m in chain.messages_json if m["role"] == "tool"]
    assert any("role_invocation_denied" in m["content"] for m in tool_msgs), tool_msgs


# ── disjoint-namespace (AC#12) ───────────────────────────────────────────────


def test_list_agent_types_and_role_registry_disjoint():
    """A colliding slug would route to the adapter path (checked first) and bypass
    the role-reject; the two namespaces MUST be disjoint."""
    assert set(list_agent_types()) & set(ROLE_REGISTRY) == set()


# ── single-sourced parser (AC#12b) ────────────────────────────────────────────


def test_assistant_and_pentester_share_the_parser():
    """Both loops call the single-sourced parse_tool_envelope (no second parser)."""
    from app.orchestrator.roles.pentester import Pentester
    pentester_src = inspect.getsource(Pentester._run_tool_loop)
    assistant_src = inspect.getsource(asvc.AssistantService._run_turn)
    assert "parse_tool_envelope" in pentester_src
    assert "parse_tool_envelope" in assistant_src
    # Neither hand-writes a second json.loads envelope parser in the loop body.
    assert "json.loads" not in pentester_src
    assert "json.loads" not in assistant_src


@pytest.mark.asyncio
async def test_parser_rejects_malformed_envelope_identically():
    """Assistant + Pentester reject a malformed / injection envelope identically
    via the shared parser."""
    from app.orchestrator.tool_envelope import parse_tool_envelope
    malformed = "not json at all <script>alert(1)</script>"
    parsed = parse_tool_envelope(malformed)
    assert parsed.parse_error == "envelope_parse_failure"

    # Assistant loop surfaces the same parse error (a parse failure never dispatches).
    session, target = _session()
    with patch.object(asvc, "resolve_session_role_client",
                      AsyncMock(return_value=_FakeClient([malformed]))):
        result = await _svc(session, target).turn(session.id, "x", _user())
    assert "envelope_parse_failure" in result.content


# ── INBOUND: assistant is not a role (PM2-D-in) ───────────────────────────────


def test_assistant_not_in_role_registry():
    assert "assistant" not in ROLE_REGISTRY


@pytest.mark.asyncio
async def test_chain_role_assistant_slug_starts_no_loop():
    """A chain role emitting {"tool":"assistant"} routes to neither an adapter nor
    a role — it is unknown, so no Assistant loop is ever started (even with
    allow_role_invocation=True, since assistant ∉ ROLE_REGISTRY)."""
    from app.orchestrator.performer import Performer
    from app.orchestrator.runtime_delegator import delegate_tool_call
    p = Performer(AsyncMock(), uuid.uuid4())
    out = await delegate_tool_call(p, "assistant", {}, allow_role_invocation=True)
    assert out["kind"] == "unknown"


# ── fail-closed missing credential RAISES (AC#10) ─────────────────────────────


@pytest.mark.asyncio
async def test_missing_cred_raises_no_smoke():
    """On the bound live lane a missing credential RAISES CredentialNotFound —
    never a smoke fixture."""
    session, target = _session()
    with patch.object(asvc, "resolve_session_role_client",
                      AsyncMock(side_effect=CredentialNotFound("no cred"))):
        with pytest.raises(CredentialNotFound):
            await _svc(session, target).turn(session.id, "x", _user())


# ── mode guard (AC#18) ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_turn_refused_when_not_assistant_mode():
    from app.orchestrator.assistant_service import AssistantModeError
    session, target = _session(mode="automation")
    with patch.object(asvc, "resolve_session_role_client", AsyncMock()):
        with pytest.raises(AssistantModeError):
            await _svc(session, target).turn(session.id, "x", _user())


# ── shared session-start scope gate + EgressMonitor symmetry (PM2-B) ──────────


@pytest.mark.asyncio
async def test_out_of_scope_session_target_rejected_before_dispatch():
    """The shared validate_session_target gate rejects an out-of-scope SESSION
    target before any dispatch (no per-call gate needed here)."""
    session, target = _session(
        domains=["evil.example.com"],  # target
        whitelist={"domains": ["scope.example.com"]},  # scope excludes it
    )
    # target domains carried on the Target row → build target dict via project.
    target.domains = ["evil.example.com"]
    executed: list[str] = []
    with patch.object(asvc, "resolve_session_role_client",
                      AsyncMock(return_value=_FakeClient([_RECON, _DONE]))), \
         patch("app.orchestrator.safety_exec.get_adapter",
               return_value=_fake_adapter("passive_recon", executed=executed)):
        result = await _svc(session, target).turn(session.id, "x", _user())
    assert result.scope_violation is True
    assert executed == [], "no dispatch after a session-target scope violation"


def test_egress_monitor_is_the_per_call_brake():
    """Symmetry with Automation (PM2-B): the SAME runtime EgressMonitor the
    Assistant seeds via bind_live_execution catches a per-call out-of-scope host.
    There is no Assistant-only pre-flight gate — this pure check proves the brake
    logic used identically on both lanes."""
    mon = EgressMonitor(uuid.uuid4(), {"domains": ["scope.example.com"]})
    assert mon._is_host_allowed("scope.example.com") is True
    assert mon._is_host_allowed("sub.scope.example.com") is True
    assert mon._is_host_allowed("evil.example.com") is False


# ── AST call-site: no adapter.execute, no parallel dispatch import (PM2-A) ─────


def test_assistant_module_reaches_dispatch_only_via_delegate_tool_call():
    src = inspect.getsource(asvc)
    # No direct adapter execution / parallel dispatch path. Adapter execution is
    # impossible without get_adapter / the safety_exec helper, both absent here;
    # the only ``.execute(`` in the module is the legitimate DB ``self._db.execute``.
    assert "get_adapter" not in src
    assert "execute_tool_through_safety_chain" not in src
    assert "safety_exec" not in src
    assert "adapter.execute" not in src
    # Reaches the ONE sanctioned chokepoint.
    assert "delegate_tool_call" in src
    # Default-deny outbound containment is used (never allow_role_invocation=True).
    assert "allow_role_invocation=False" in src
    assert "allow_role_invocation=True" not in src
