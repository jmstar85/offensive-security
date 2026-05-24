"""Role abstract class + Registry tests (v4.0 P1)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.orchestrator.roles.base import Role, RoleResult
from app.orchestrator.roles.registry import (
    get_role,
    list_roles,
    register_role,
)


def test_role_is_abstract():
    """`Role` is an ABC — Python's metaclass refuses direct instantiation
    when `run()` is not overridden. This is the strongest contract we can
    enforce at construction time and matches PentAGI's role contract."""
    with pytest.raises(TypeError, match="abstract"):
        Role(
            name="abstract",
            system_prompt="...",
            llm_model="claude-sonnet-4-6",
        )


def test_concrete_subclass_passes_contract():
    """A concrete Role subclass overriding `run` satisfies the contract."""

    @dataclass
    class TestableRole(Role):
        async def run(self, performer: Any, context: dict[str, Any]) -> RoleResult:
            return RoleResult(role_name=self.name, finished=True, tool_calls=0)

    role = TestableRole(
        name="testable",
        system_prompt="test",
        llm_model="claude-sonnet-4-6",
        tools_allowed=["nmap"],
        max_tool_calls=5,
    )
    import asyncio

    result = asyncio.run(role.run(performer=None, context={}))
    assert result.role_name == "testable"
    assert result.finished is True


def test_register_get_list_roles(monkeypatch):
    """Registry round-trip: register → get → list."""
    monkeypatch.setattr(
        "app.orchestrator.roles.registry.ROLE_REGISTRY", {}
    )

    @dataclass
    class RoleA(Role):
        slug = "role-a"

        async def run(self, performer, context):
            return RoleResult(role_name=self.name)

    @dataclass
    class RoleB(Role):
        slug = "role-b"

        async def run(self, performer, context):
            return RoleResult(role_name=self.name)

    register_role(RoleA)
    register_role(RoleB)

    assert "role-a" in list_roles()
    assert "role-b" in list_roles()
    assert get_role("role-a") is RoleA
    assert get_role("role-b") is RoleB


def test_register_rejects_non_role_class():
    """register_role(non-Role) raises TypeError."""

    class NotARole:
        pass

    with pytest.raises(TypeError):
        register_role(NotARole)  # type: ignore[arg-type]


def test_get_role_missing_raises_keyerror(monkeypatch):
    """get_role(missing_slug) → KeyError with helpful message."""
    monkeypatch.setattr(
        "app.orchestrator.roles.registry.ROLE_REGISTRY", {}
    )
    with pytest.raises(KeyError, match="is not registered"):
        get_role("nope")
