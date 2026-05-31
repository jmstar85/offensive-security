"""W0/PR0.1 placeholder — full seed_xbow isolation invariant lands in W2b/PR2b.1.

When ``backend/app/roles/seed_xbow.py`` lands, this file is replaced with
two AST assertions:
  - ``seed_xbow.py`` is NOT imported from ``backend/app/main.py`` at
    module level (it must only be imported by a startup hook gated on
    ``osa_xbow_families_enabled``); MF5 invariant.
  - ``roles/seed.py`` does NOT reference any symbol from ``seed_xbow``
    (preservation of the byte-identical Minimal-6 role registration).

Until W2b lands, this file skips at collection so neither pytest nor the
CODEOWNERS coverage test trips on the missing source.
"""
import pytest

pytest.skip(
    "seed_xbow.py not yet present — placeholder until W2b/PR2b.1",
    allow_module_level=True,
)
