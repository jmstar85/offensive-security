"""Role catalog for the v4.0 Performer engine (PentAGI port).

In P1 this module exposes the abstract `Role` base class, the in-memory
`ROLE_REGISTRY` dict, and the `memorist_embedding` singleton loader used by
`main.py`'s startup warm-up. The concrete 6 roles (Generator, Pentester,
Memorist, Adviser, Reflector, Reporter) ship in P2a.

Public surface:
- `Role` — abstract dataclass for any role
- `ROLE_REGISTRY` — global dict (slug → Role class)
- `register_role(role_cls)` — register decorator/function
- `get_role(name)` — lookup by slug
- `list_roles()` — list registered slugs
- `memorist_embedding` — submodule with `get_or_load_model()` (used by startup hook)
"""
from app.orchestrator.roles.base import Role, RoleResult
from app.orchestrator.roles.registry import (
    ROLE_REGISTRY,
    get_role,
    list_roles,
    register_role,
)
from app.orchestrator.roles import memorist_embedding

__all__ = [
    "Role",
    "RoleResult",
    "ROLE_REGISTRY",
    "register_role",
    "get_role",
    "list_roles",
    "memorist_embedding",
]
