"""PR4 — ModelSelector catalog + three-way default reconciliation (PM3).

A non-admin can now select the opus-4-8 session default (no 403) AND the cheaper
sonnet-4-6, while opus-4-6 stays admin-gated (existing RBAC unchanged). The
internal-role fallback stays sonnet-4-6 (no cost inversion).
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.user import UserRole
from app.orchestrator.model_selector import ModelSelector
from app.orchestrator.roles.llm_provider import (
    resolve_role_llm_model,
    resolve_role_send_model,
)


def _user(role):
    return SimpleNamespace(id="u", email="u@x", role=role)


# ── catalog resolution ──────────────────────────────────────────────────────


def test_non_admin_can_select_session_default_opus_4_8_no_403():
    sel = ModelSelector()
    m = sel.resolve("claude-opus-4-8", _user(UserRole.MEMBER))
    assert m.model_id == "claude-opus-4-8"
    assert m.is_admin_only is False


def test_non_admin_can_select_sonnet_4_6():
    sel = ModelSelector()
    m = sel.resolve("claude-sonnet-4-6", _user(UserRole.MEMBER))
    assert m.model_id == "claude-sonnet-4-6"
    assert m.is_admin_only is False


def test_non_admin_opus_4_6_rejected_403():
    sel = ModelSelector()
    with pytest.raises(HTTPException) as ei:
        sel.resolve("claude-opus-4-6", _user(UserRole.MEMBER))
    assert ei.value.status_code == 403


def test_admin_can_select_all_models():
    sel = ModelSelector()
    admin = _user(UserRole.ADMIN)
    assert sel.resolve("claude-opus-4-8", admin).model_id == "claude-opus-4-8"
    assert sel.resolve("claude-sonnet-4-6", admin).model_id == "claude-sonnet-4-6"
    m = sel.resolve("claude-opus-4-6", admin)
    assert m.model_id == "claude-opus-4-6"
    assert m.is_admin_only is True


def test_unknown_model_rejected_400():
    sel = ModelSelector()
    with pytest.raises(HTTPException) as ei:
        sel.resolve("gpt-9", _user(UserRole.ADMIN))
    assert ei.value.status_code == 400


# ── internal-role fallback regression (no cost inversion, PM3) ──────────────


def test_internal_role_default_stays_sonnet_not_opus():
    # The internal-role fallback must NOT be promoted to the opus-4-8 session
    # default — otherwise every internal anthropic role would run opus.
    assert resolve_role_llm_model() == "claude-sonnet-4-6"
    assert resolve_role_llm_model() == settings.anthropic_default_model
    assert resolve_role_llm_model() != settings.session_default_model

    assert resolve_role_send_model(None) == settings.anthropic_default_model_anthropic_id
    assert resolve_role_send_model(None) != settings.session_default_model_anthropic_id
