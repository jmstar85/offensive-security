"""PR9 — osa_multi_provider_llm default-ON + Fernet-required validator + fail-closed.

Covers:
- (a) osa_multi_provider_llm defaults True; the resulting default flag tuple is
  T3 (multi_provider + coordinator + xbow_families), a supported production
  topology (validate_flag_topology accepts it).
- (b) Settings construction FAILS FAST in production when the flag is ON but
  CREDENTIAL_FERNET_KEY is missing; passes when the key is present; and is gated
  to production (dev/test may run the flag ON with no key — keys are injected
  per-test), so the module-level ``settings = Settings()`` import stays green.
- (c) NO-CREDENTIAL FAIL-CLOSED on BOTH paths: with the flag ON and no stored
  Anthropic credential for the user, the settings.anthropic_api_key fallback is
  disabled (credential_resolver.py:61-63), so
    (i)  the fresh-plan default engine run resolves its client via
         LLMRouter.route(db, "anthropic", user_id=actor) → CredentialNotFound, and
    (ii) the interview/chat turn (flag-ON path routes through
         LLMRouter.route(user_id=...) with CURRENT_USER_ID set at the
         send_message entrypoint — PR7 set-site) → CredentialNotFound.
  The contrapositive (flag OFF → fallback returns the process-env key) proves the
  fallback is gated on the flag, not always-on.
"""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.core import config
from app.core.config import Settings
from app.core.feature_flag_validator import _T3, _tuple_for, validate_flag_topology
from app.orchestrator.llm import credential_resolver as cred_mod
from app.orchestrator.llm.context import with_user_context
from app.orchestrator.llm.credential_resolver import CredentialNotFound
from app.orchestrator.llm.router import LLMRouter


# --------------------------------------------------------------------------- #
# (a) default posture: flag ON → default tuple is T3 (supported)
# --------------------------------------------------------------------------- #

def test_osa_multi_provider_llm_defaults_true():
    fresh = Settings(_env_file=None)
    assert fresh.osa_multi_provider_llm is True


def test_default_flag_tuple_is_t3_supported():
    """Flipping osa_multi_provider_llm ON yields exactly T3 — a supported tuple,
    so a production start with the shipped defaults is accepted."""
    fresh = Settings(_env_file=None)
    assert _tuple_for(fresh) == _T3

    prod = Settings(_env_file=None, environment="production", credential_fernet_key="x")
    assert validate_flag_topology(prod) is None  # T3 accepted in production


# --------------------------------------------------------------------------- #
# (b) Fernet-required fail-fast validator (production-gated)
# --------------------------------------------------------------------------- #

def test_production_multi_provider_requires_fernet_key():
    """Flag ON + production + no Fernet key → construction fails fast."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            environment="production",
            osa_multi_provider_llm=True,
            credential_fernet_key="",
        )
    assert "CREDENTIAL_FERNET_KEY" in str(exc_info.value)


def test_production_multi_provider_with_fernet_key_ok():
    """Flag ON + production + a Fernet key present → construction succeeds."""
    s = Settings(
        _env_file=None,
        environment="production",
        osa_multi_provider_llm=True,
        credential_fernet_key="base64-fernet-key",
    )
    assert s.osa_multi_provider_llm is True


def test_production_flag_off_needs_no_fernet_key():
    """Flag OFF → the Fernet key is not required even in production."""
    s = Settings(
        _env_file=None,
        environment="production",
        osa_multi_provider_llm=False,
        credential_fernet_key="",
    )
    assert s.osa_multi_provider_llm is False


def test_dev_multi_provider_without_fernet_key_is_permitted():
    """The check is production-gated (mirrors validate_flag_topology): dev/test can
    run the flag ON with no key so the module-level Settings() import stays green
    and tests inject a Fernet key per-test."""
    s = Settings(
        _env_file=None,
        environment="dev",
        osa_multi_provider_llm=True,
        credential_fernet_key="",
    )
    assert s.osa_multi_provider_llm is True


# --------------------------------------------------------------------------- #
# (c) no-credential fail-closed on BOTH paths (flag ON disables the fallback)
# --------------------------------------------------------------------------- #

class _NoRowResult:
    def scalar_one_or_none(self):
        return None


class _NoRowDB:
    """Minimal fake AsyncSession: every query returns zero credential rows."""

    async def execute(self, *args, **kwargs):
        return _NoRowResult()


@pytest.mark.asyncio
async def test_fresh_plan_engine_run_fails_closed_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(c)(i) Fresh-plan default engine run: the role client is resolved via
    LLMRouter.route(db, "anthropic", user_id=actor). Flag ON + no stored
    credential → CredentialNotFound, EVEN with anthropic_api_key set (the
    process-env fallback is disabled)."""
    monkeypatch.setattr(config.settings, "osa_multi_provider_llm", True)
    monkeypatch.setattr(config.settings, "anthropic_api_key", "sk-env-fallback")

    actor = uuid.uuid4()
    with pytest.raises(CredentialNotFound):
        await LLMRouter().route(db=_NoRowDB(), provider="anthropic", user_id=actor)


@pytest.mark.asyncio
async def test_interview_chat_turn_fails_closed_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(c)(ii) Interview/chat turn: the flag-ON path routes through
    LLMRouter.route(user_id=None) which reads CURRENT_USER_ID (set at the
    send_message entrypoint via with_user_context — PR7 set-site). Flag ON + no
    stored credential → CredentialNotFound, EVEN with anthropic_api_key set."""
    monkeypatch.setattr(config.settings, "osa_multi_provider_llm", True)
    monkeypatch.setattr(config.settings, "anthropic_api_key", "sk-env-fallback")

    actor = uuid.uuid4()
    with with_user_context(actor):
        with pytest.raises(CredentialNotFound):
            # user_id=None → resolver reads the contextvar set above.
            await LLMRouter().route(db=_NoRowDB(), provider="anthropic", user_id=None)


@pytest.mark.asyncio
async def test_fallback_active_when_flag_off_contrapositive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contrapositive: with the flag OFF the anthropic_api_key process-env
    fallback IS honored, so the same no-credential setup resolves the env key
    instead of raising. This proves the fail-closed behavior is gated on the
    flag, not unconditional."""
    monkeypatch.setattr(config.settings, "osa_multi_provider_llm", False)
    monkeypatch.setattr(config.settings, "anthropic_api_key", "sk-env-fallback")
    # Avoid constructing the real Anthropic SDK client from the resolved key.
    sentinel = object()
    monkeypatch.setattr(
        LLMRouter, "get_client", lambda self, provider, api_key="": sentinel
    )

    actor = uuid.uuid4()
    result = await LLMRouter().route(db=_NoRowDB(), provider="anthropic", user_id=actor)
    assert result is sentinel  # fallback returned the env key; no raise
