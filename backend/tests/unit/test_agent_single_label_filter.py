"""Fix 5 (session 0f9c5646 defense-in-depth): bogus single-label domains like
"jarvis" (which the project Target carried) must be dropped from adapter targets
when a resolvable target co-exists — mirroring NmapAdapter — but KEPT when they
are the only target (internal engagements with bare hostnames).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.agents.base import filter_resolvable_targets
from app.agents.dnsx import DnsxAdapter
from app.agents.httpx_tool import HttpxAdapter
from app.agents.nuclei import NucleiAdapter
from app.agents.subfinder import SubfinderAdapter
from app.agents.wappalyzer import WappalyzerAdapter


def _uarg(cmd: list[str]) -> str:
    return cmd[cmd.index("-u") + 1]


def _darg(cmd: list[str]) -> str:
    return cmd[cmd.index("-d") + 1]


# ── shared helper ────────────────────────────────────────────────────────────


def test_filter_drops_single_label_only_when_resolvable_coexists():
    assert filter_resolvable_targets(["jarvis", "example.com"]) == ["example.com"]
    assert filter_resolvable_targets(["jarvis"]) == ["jarvis"]
    assert filter_resolvable_targets(["10.0.0.1", "jarvis"]) == ["10.0.0.1"]
    assert filter_resolvable_targets([]) == ["127.0.0.1"]


# ── nuclei ───────────────────────────────────────────────────────────────────


def test_nuclei_drops_jarvis_when_real_target_coexists():
    cmd = NucleiAdapter(backend=MagicMock()).build_command(
        {"domains": ["jarvis", "example.com"], "ip_ranges": []}, {}
    )
    assert "example.com" in _uarg(cmd)
    assert "jarvis" not in _uarg(cmd)


def test_nuclei_keeps_lone_jarvis_and_falls_back_when_empty():
    keep = NucleiAdapter(backend=MagicMock()).build_command(
        {"domains": ["jarvis"], "ip_ranges": []}, {}
    )
    assert _uarg(keep) == "jarvis"
    empty = NucleiAdapter(backend=MagicMock()).build_command({"domains": [], "ip_ranges": []}, {})
    assert _uarg(empty) == "127.0.0.1"


# ── httpx ────────────────────────────────────────────────────────────────────


def test_httpx_drops_jarvis_when_real_domain_coexists():
    cmd = HttpxAdapter(backend=MagicMock()).build_command(
        {"domains": ["jarvis", "example.com"]}, {}
    )
    assert "-u" in cmd and "example.com" in cmd
    assert "jarvis" not in cmd


def test_httpx_keeps_lone_single_label():
    cmd = HttpxAdapter(backend=MagicMock()).build_command({"domains": ["jarvis"]}, {})
    assert _uarg(cmd) == "jarvis"


# ── subfinder / dnsx (first-domain pattern) ─────────────────────────────────


def test_subfinder_prefers_resolvable_domain():
    cmd = SubfinderAdapter(backend=MagicMock()).build_command(
        {"domains": ["jarvis", "example.com"]}, {}
    )
    assert _darg(cmd) == "example.com"
    lone = SubfinderAdapter(backend=MagicMock()).build_command({"domains": ["jarvis"]}, {})
    assert _darg(lone) == "jarvis"


def test_dnsx_prefers_resolvable_domain():
    cmd = DnsxAdapter(backend=MagicMock()).build_command(
        {"domains": ["jarvis", "example.com"]}, {}
    )
    assert _darg(cmd) == "example.com"


# ── wappalyzer (url) ─────────────────────────────────────────────────────────


def test_wappalyzer_prefers_resolvable_domain_in_url():
    cmd = WappalyzerAdapter(backend=MagicMock()).build_command(
        {"domains": ["jarvis", "example.com"]}, {}
    )
    assert cmd[0] == "https://example.com"
