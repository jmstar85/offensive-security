"""Per-session, per-role client resolution (PR3 / PM1, Blocking 2, Improvement 3).

Covers ``resolve_session_role_client`` + ``build_client_factory`` +
``provider_of`` / ``default_model_for``:
- ``str`` actor_id is coerced to ``uuid.UUID`` and forwarded EXPLICITLY to route
  (zero-row regression guard).
- Missing credential raises ``CredentialNotFound`` (never ``None``).
- Provider precedence: NULL ``llm_provider_pref`` → global switch fallback;
  explicit pref overrides; empty ``model_map`` → session default; role override
  wins.
- ``client_factory(role)`` resolves per invocation (fresh route each call — no
  cached client); a mid-session revoke is honored on the next invocation;
  ``last_used_at``/audit is written on every resolve (touch-count spy).

The DB/route layer is mocked to isolate resolver logic.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.orchestrator.llm.credential_resolver import CredentialNotFound
from app.orchestrator.llm.router import LLMRouter
from app.orchestrator.roles.llm_provider import (
    build_client_factory,
    default_model_for,
    provider_of,
    resolve_session_role_client,
)


def _session(model_map=None, llm_provider_pref=None, model_id=None) -> SimpleNamespace:
    return SimpleNamespace(
        model_map={} if model_map is None else model_map,
        llm_provider_pref=llm_provider_pref,
        model_id=model_id,
    )


@pytest.fixture()
def route_spy(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch ``LLMRouter.route`` with an AsyncMock.

    AsyncMock is not a descriptor, so ``LLMRouter().route(db, provider, ...)``
    calls it WITHOUT ``self`` — recorded call args are ``(db, provider)`` +
    ``user_id`` kwarg.
    """
    spy = AsyncMock(return_value=object())
    monkeypatch.setattr(LLMRouter, "route", spy)
    return spy


# ── provider_of / default_model_for ─────────────────────────────────────────

def test_provider_of_mapping() -> None:
    assert provider_of("claude-opus-4-8") == "anthropic"
    assert provider_of("claude-sonnet-4-6") == "anthropic"
    assert provider_of("gpt-4o-mini") == "openai"
    assert provider_of("o1-preview") == "openai"
    assert provider_of("o3-mini") == "openai"
    assert provider_of("qwen3-14b-96k:latest") == "ollama"
    assert provider_of("llama3:8b") == "ollama"


def test_default_model_for_mapping() -> None:
    assert default_model_for("ollama") == settings.ollama_model
    assert default_model_for("anthropic") == settings.anthropic_default_model
    assert default_model_for("openai") == getattr(settings, "openai_default_model", "gpt-4o")


# ── UUID coercion + explicit forwarding ─────────────────────────────────────

@pytest.mark.asyncio
async def test_str_actor_id_coerced_to_uuid_and_forwarded_explicitly(
    route_spy: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "osa_llm_provider", "anthropic")
    uid = uuid.uuid4()
    session = _session()

    await resolve_session_role_client(
        db=None, session=session, role="pentester", user_id=str(uid)
    )

    assert route_spy.await_count == 1
    _, kwargs = route_spy.await_args
    assert kwargs["user_id"] == uid  # coerced
    assert isinstance(kwargs["user_id"], uuid.UUID)  # zero-row regression guard


# ── fail-closed on missing credential ───────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_credential_raises_credential_not_found_never_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _raise(*args, **kwargs):
        raise CredentialNotFound("missing")

    monkeypatch.setattr(LLMRouter, "route", _raise)
    monkeypatch.setattr(settings, "osa_llm_provider", "anthropic")
    session = _session()

    with pytest.raises(CredentialNotFound):
        await resolve_session_role_client(
            db=None, session=session, role="pentester", user_id=uuid.uuid4()
        )


# ── provider/model precedence (Principle 10) ────────────────────────────────

@pytest.mark.asyncio
async def test_null_provider_pref_falls_back_to_global_switch(
    route_spy: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "osa_llm_provider", "ollama")
    session = _session(model_map={}, llm_provider_pref=None)

    await resolve_session_role_client(
        db=None, session=session, role="pentester", user_id=uuid.uuid4()
    )

    args, _ = route_spy.await_args
    assert args[1] == "ollama"  # GLOBAL SWITCH preserved (E2E-preserving)


@pytest.mark.asyncio
async def test_explicit_provider_pref_overrides_global_switch(
    route_spy: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "osa_llm_provider", "anthropic")  # global says anthropic
    session = _session(
        model_map={}, llm_provider_pref="ollama", model_id="qwen3-14b-96k:latest"
    )

    await resolve_session_role_client(
        db=None, session=session, role="pentester", user_id=uuid.uuid4()
    )

    args, _ = route_spy.await_args
    assert args[1] == "ollama"  # explicit pref wins over the global switch


@pytest.mark.asyncio
async def test_empty_model_map_uses_session_default_provider(
    route_spy: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "osa_llm_provider", "openai")  # must NOT be used
    session = _session(
        model_map={}, llm_provider_pref="anthropic", model_id="claude-opus-4-8"
    )

    await resolve_session_role_client(
        db=None, session=session, role="generator", user_id=uuid.uuid4()
    )

    args, _ = route_spy.await_args
    assert args[1] == "anthropic"  # session default provider


@pytest.mark.asyncio
async def test_model_map_role_override_wins(
    route_spy: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "osa_llm_provider", "anthropic")
    # session default provider = anthropic, but pentester overridden to an ollama model.
    session = _session(
        model_map={"pentester": "qwen3-14b-96k:latest"},
        llm_provider_pref="anthropic",
        model_id="claude-opus-4-8",
    )

    await resolve_session_role_client(
        db=None, session=session, role="pentester", user_id=uuid.uuid4()
    )
    args, _ = route_spy.await_args
    assert args[1] == "ollama"  # provider_of(qwen…) == ollama, override wins

    # A non-overridden role still uses the session default provider.
    route_spy.reset_mock()
    await resolve_session_role_client(
        db=None, session=session, role="generator", user_id=uuid.uuid4()
    )
    args2, _ = route_spy.await_args
    assert args2[1] == "anthropic"


# ── client_factory: per-invocation resolution, no session cache ─────────────

@pytest.mark.asyncio
async def test_client_factory_resolves_per_invocation_fresh_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "osa_llm_provider", "anthropic")
    c1, c2, c3 = object(), object(), object()
    spy = AsyncMock(side_effect=[c1, c2, c3])
    monkeypatch.setattr(LLMRouter, "route", spy)
    session = _session(
        model_map={}, llm_provider_pref="anthropic", model_id="claude-opus-4-8"
    )

    factory = build_client_factory(db=None, session=session, actor_id=uuid.uuid4())
    r1 = await factory("pentester")
    r2 = await factory("generator")
    r3 = await factory("adviser")

    assert (r1, r2, r3) == (c1, c2, c3)  # a fresh client each call (no cached client)
    assert spy.await_count == 3  # route() invoked per role invocation


@pytest.mark.asyncio
async def test_client_factory_honors_mid_session_revoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "osa_llm_provider", "anthropic")
    good, recreated = object(), object()
    spy = AsyncMock(side_effect=[good, CredentialNotFound("revoked"), recreated])
    monkeypatch.setattr(LLMRouter, "route", spy)
    session = _session(
        model_map={}, llm_provider_pref="anthropic", model_id="claude-opus-4-8"
    )

    factory = build_client_factory(db=None, session=session, actor_id=uuid.uuid4())
    assert await factory("pentester") is good  # first invocation OK

    with pytest.raises(CredentialNotFound):  # credential revoked mid-session
        await factory("pentester")

    # Recreated → next invocation succeeds (fresh route(), no cached failure/client).
    assert await factory("pentester") is recreated
    assert spy.await_count == 3


@pytest.mark.asyncio
async def test_last_used_touch_written_on_every_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every resolve reaches ``resolve_provider_credential`` (which bumps
    ``last_used_at`` / writes the credential-touch audit) — proving
    audit-every-touch with no session-lived cache."""
    monkeypatch.setattr(settings, "osa_llm_provider", "anthropic")
    from app.orchestrator.llm import credential_resolver as cred_mod

    touch_spy = AsyncMock(return_value="sk-key")
    monkeypatch.setattr(cred_mod, "resolve_provider_credential", touch_spy)
    # Avoid constructing the real Anthropic SDK client — route() runs for real
    # so the touch (resolve_provider_credential) is exercised per call.
    sentinel = object()
    monkeypatch.setattr(
        LLMRouter, "get_client", lambda self, provider, api_key="": sentinel
    )
    session = _session(
        model_map={}, llm_provider_pref="anthropic", model_id="claude-opus-4-8"
    )

    factory = build_client_factory(db=None, session=session, actor_id=uuid.uuid4())
    for _ in range(3):
        assert await factory("pentester") is sentinel

    assert touch_spy.await_count == 3  # last_used_at bumped on EVERY resolve
