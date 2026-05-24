"""Unit tests for ModelSelector RBAC (plan v3.2.1 §1.2)."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.user import UserRole
from app.orchestrator.model_selector import ModelSelector


def _user(role: str):
    return SimpleNamespace(id="u", email="u@x", role=role)


def test_non_admin_default_model_ok():
    sel = ModelSelector()
    m = sel.resolve("claude-sonnet-4-6", _user(UserRole.MEMBER))
    assert m.model_id == "claude-sonnet-4-6"
    assert m.is_admin_only is False


def test_admin_can_select_opus():
    sel = ModelSelector()
    m = sel.resolve("claude-opus-4-6", _user(UserRole.ADMIN))
    assert m.model_id == "claude-opus-4-6"
    assert m.is_admin_only is True


def test_non_admin_opus_rejected_403():
    sel = ModelSelector()
    with pytest.raises(HTTPException) as ei:
        sel.resolve("claude-opus-4-6", _user(UserRole.MEMBER))
    assert ei.value.status_code == 403


def test_none_falls_back_to_default():
    sel = ModelSelector()
    m = sel.resolve(None, _user(UserRole.MEMBER))
    assert m.model_id == "claude-sonnet-4-6"


def test_unknown_model_rejected_400():
    sel = ModelSelector()
    with pytest.raises(HTTPException) as ei:
        sel.resolve("gpt-9", _user(UserRole.ADMIN))
    assert ei.value.status_code == 400
