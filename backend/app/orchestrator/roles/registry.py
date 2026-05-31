"""In-memory role registry for the v4.0 Performer engine.

P1 ships an empty registry + the public surface. P2a populates it via
`backend/app/orchestrator/roles/seed.py` which registers the 6 v1 roles.

This is the role-level analog to `backend/app/agents/registry.py` (which lists
the 11 AgentAdapters). Both registries are read at session start time by the
Performer to compose the role catalog + tool palette for the active session.
"""
from __future__ import annotations

from typing import Type

from app.orchestrator.roles.base import Role


ROLE_REGISTRY: dict[str, Type[Role]] = {}


def register_role(role_cls: Type[Role]) -> Type[Role]:
    """Register a concrete Role subclass.

    Use as a class decorator or call directly. Concrete v1 roles register at
    module-import time via `backend/app/orchestrator/roles/seed.py` (P2a).
    """
    if not issubclass(role_cls, Role):
        raise TypeError(f"{role_cls.__name__} must subclass Role")
    # Each Role subclass advertises its slug via a class-level `slug` attribute
    # (set in P2a concrete subclasses). For the abstract base + tests, we
    # tolerate a missing `slug` and fall back to the lowercased class name.
    slug = getattr(role_cls, "slug", None) or role_cls.__name__.lower()
    ROLE_REGISTRY[slug] = role_cls
    return role_cls


def get_role(name: str) -> Type[Role]:
    """Look up a registered Role class by slug. Raises KeyError if missing."""
    if name not in ROLE_REGISTRY:
        raise KeyError(
            f"Role {name!r} is not registered. "
            f"Known roles: {sorted(ROLE_REGISTRY.keys())}"
        )
    return ROLE_REGISTRY[name]


def list_roles() -> list[str]:
    """Return all registered role slugs (sorted, deterministic)."""
    return sorted(ROLE_REGISTRY.keys())


def lazy_register_if_enabled(flag: bool, role_module_path: str = "app.orchestrator.roles.seed_xbow") -> bool:
    """Import the seed_xbow module and call its _register_all() ONLY when flag is True.

    Returns True if registration ran, False if skipped. Idempotent — repeated
    calls with flag=True are safe.
    """
    if not flag:
        return False
    import importlib
    module = importlib.import_module(role_module_path)
    module._register_all()
    return True
