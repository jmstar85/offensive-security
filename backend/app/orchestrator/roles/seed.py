"""Role-seed module (v4.0 P2a).

Importing this module imports each of the 6 Minimal v1 role modules; the
side-effect of those imports is `register_role(...)` calls that populate
`ROLE_REGISTRY` in `backend/app/orchestrator/roles/registry.py`.

Callers (e.g. `Performer.run_session`, or a test fixture) should
`import app.orchestrator.roles.seed` once at startup to guarantee the
registry is populated. After that, `list_roles()` returns the 6 slugs and
`get_role("pentester")` resolves the class.

The 8 v3.4+ roles are intentionally not imported here.
"""
# Importing the modules is the only side-effect we need; `register_role`
# decorators run during import.
from app.orchestrator.roles import (
    adviser,  # noqa: F401  (registers Adviser)
    generator,  # noqa: F401  (registers Generator)
    memorist,  # noqa: F401  (registers Memorist)
    pentester,  # noqa: F401  (registers Pentester)
    reflector,  # noqa: F401  (registers Reflector)
    reporter,  # noqa: F401  (registers Reporter)
)

# Sanity invariant: every Minimal 6 role is registered.
from app.orchestrator.roles.registry import ROLE_REGISTRY

MINIMAL_6_ROLES = frozenset(
    {"generator", "pentester", "memorist", "adviser", "reflector", "reporter"}
)


def assert_registered() -> None:
    """Raise AssertionError if any of the 6 v1 roles are missing.

    Called at startup (and from tests) to guarantee the registry is healthy
    before the Performer engine starts dispatching.
    """
    missing = MINIMAL_6_ROLES - set(ROLE_REGISTRY.keys())
    if missing:
        raise AssertionError(
            f"Role seeding incomplete. Missing: {sorted(missing)}. "
            f"Registered: {sorted(ROLE_REGISTRY.keys())}."
        )


assert_registered()
