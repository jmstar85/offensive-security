"""PR-7 — registry regression guard (Pre-mortem F4 / Principle 5).

For every existing typed slug, ``get_adapter`` must return an adapter whose
backend is a ``DockerBackend`` instance — NEVER a ``KaliBackend``. This is
the load-bearing test that the parallel Kali path has not silently
migrated any legacy adapter.

Note: there are 10 legacy slugs (the plan summary references 9 + wappalyzer
as a recent active-recon addition); the AC list in PR-9 enumerates all of
them. We assert against the canonical list defined here.
"""
from __future__ import annotations

import pytest

from app.agents.backends.docker import DockerBackend
from app.agents.backends.kali import KaliBackend
from app.agents.registry import get_adapter

LEGACY_SLUGS: tuple[str, ...] = (
    "nmap", "nuclei", "metasploit", "pyrit",
    "passive_recon", "subfinder", "dnsx", "httpx",
    "cloudenum", "wappalyzer",
)


@pytest.mark.parametrize("slug", LEGACY_SLUGS)
def test_legacy_slug_routes_to_docker_backend(slug):
    adapter = get_adapter(slug)
    assert isinstance(adapter.backend, DockerBackend)
    assert not isinstance(adapter.backend, KaliBackend)


def test_kali_slugs_route_to_kali_backend():
    for slug in ("kali_gobuster", "kali_sqlmap", "kali_nikto"):
        adapter = get_adapter(slug)
        assert isinstance(adapter.backend, KaliBackend)
        assert not isinstance(adapter.backend, DockerBackend)
