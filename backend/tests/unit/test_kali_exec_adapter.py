"""PR-5 — KaliExecAdapter build_command/parse_output + registry wiring."""
from __future__ import annotations

import pytest

from app.agents.backends.docker import DockerBackend
from app.agents.backends.kali import KaliBackend
from app.agents.base import RiskLevel
from app.agents.kali_exec import (
    KaliExecAdapter,
    KaliGobusterAdapter,
    KaliNiktoAdapter,
    KaliSqlmapAdapter,
)
from app.agents.kali_whitelist import SafetyViolation
from app.agents.registry import (
    get_adapter,
    get_tool_entry,
    list_agent_types,
    palette_for_domain,
)


# --- build_command -----------------------------------------------------------

@pytest.mark.parametrize("adapter_cls,slug,args,expected_binary", [
    (KaliGobusterAdapter, "gobuster",
     ["dir", "-u", "http://t/", "-w", "/wordlists/c.txt"],
     "/usr/bin/gobuster"),
    (KaliSqlmapAdapter, "sqlmap",
     ["-u", "http://t/q?id=1", "--batch"],
     "/usr/bin/sqlmap"),
    (KaliNiktoAdapter, "nikto",
     ["-h", "http://t/", "-Format", "json"],
     "/usr/bin/nikto"),
])
def test_build_command_passes_through_args(adapter_cls, slug, args, expected_binary):
    adapter = adapter_cls(backend=KaliBackend())
    cmd = adapter.build_command({}, {"tool_slug": slug, "args": args})
    assert cmd[0] == expected_binary
    assert cmd[1:] == args


def test_build_command_rejects_deny_flag():
    adapter = KaliSqlmapAdapter(backend=KaliBackend())
    with pytest.raises(SafetyViolation):
        adapter.build_command({}, {"tool_slug": "sqlmap", "args": ["--os-shell"]})


def test_build_command_missing_slug_raises():
    adapter = KaliExecAdapter(backend=KaliBackend())  # base, no tool_slug
    with pytest.raises(SafetyViolation, match="missing_tool_slug"):
        adapter.build_command({}, {"args": []})


def test_build_command_slug_mismatch_raises():
    adapter = KaliGobusterAdapter(backend=KaliBackend())
    with pytest.raises(SafetyViolation, match="slug_mismatch"):
        adapter.build_command({}, {"tool_slug": "sqlmap", "args": []})


# --- parse_output ------------------------------------------------------------

GOBUSTER_SAMPLE = """\
===============================================================
Gobuster v3.6
===============================================================
/admin                (Status: 200) [Size: 1234]
/login.php            (Status: 302) [Size: 0]
/private              (Status: 403) [Size: 287]
"""


def test_parse_gobuster_extracts_findings():
    adapter = KaliGobusterAdapter(backend=KaliBackend())
    result = adapter.parse_output(GOBUSTER_SAMPLE)
    assert result.success
    paths = {f["path"] for f in result.findings if f["type"] == "directory_found"}
    assert paths == {"/admin", "/login.php", "/private"}


SQLMAP_SAMPLE = """\
sqlmap identified the following injection point(s) with a total of N HTTP(s) requests:
---
Parameter: id (GET)
    Type: boolean-based blind
    Title: AND boolean-based blind - WHERE or HAVING clause
    Payload: id=1 AND 1=1
---
"""


def test_parse_sqlmap_extracts_finding():
    adapter = KaliSqlmapAdapter(backend=KaliBackend())
    result = adapter.parse_output(SQLMAP_SAMPLE)
    assert result.success
    assert len(result.findings) == 1
    f = result.findings[0]
    assert f["type"] == "sql_injection"
    assert f["parameter"] == "id"
    assert f["location"] == "GET"
    assert f["technique"] == "boolean-based blind"
    assert "id=1 AND 1=1" in f["payload"]
    assert f["severity"] == "high"


NIKTO_JSON_SAMPLE = """[
  {
    "host": "target",
    "vulnerabilities": [
      {"id": "OSVDB-3092", "msg": "/admin: This might be interesting"},
      {"id": "OSVDB-3268", "msg": "Directory indexing found"}
    ]
  }
]"""


def test_parse_nikto_json_extracts_vulns():
    adapter = KaliNiktoAdapter(backend=KaliBackend())
    result = adapter.parse_output(NIKTO_JSON_SAMPLE)
    assert result.success
    ids = {f["id"] for f in result.findings}
    assert ids == {"OSVDB-3092", "OSVDB-3268"}


def test_parse_output_rejects_unregistered_slug():
    # Base class with no slug must refuse to fall back.
    adapter = KaliExecAdapter(backend=KaliBackend())
    with pytest.raises(NotImplementedError, match="requires a tool_slug"):
        adapter.parse_output("anything")


# --- Registry wiring ---------------------------------------------------------

def test_three_kali_entries_registered():
    slugs = set(list_agent_types())
    assert {"kali_gobuster", "kali_sqlmap", "kali_nikto"} <= slugs


@pytest.mark.parametrize("slug,expected_tier,expected_band,destructive,caps_subset", [
    ("kali_gobuster", "active_recon", RiskLevel.MEDIUM, False, {"dir_brute"}),
    ("kali_sqlmap", "active_exploit", RiskLevel.HIGH, True, {"sqli_detect"}),
    ("kali_nikto", "active_recon", RiskLevel.MEDIUM, False, {"web_vuln_scan"}),
])
def test_kali_tool_entry_metadata(slug, expected_tier, expected_band, destructive, caps_subset):
    entry = get_tool_entry(slug)
    assert entry is not None
    assert entry.tier == expected_tier
    assert entry.default_risk_band is expected_band
    assert entry.is_destructive_capable is destructive
    assert caps_subset <= set(entry.capabilities)
    assert entry.applicable_domain_tags == frozenset({"web", "api"})


def test_get_adapter_routes_kali_to_kali_backend():
    adapter = get_adapter("kali_gobuster")
    assert isinstance(adapter, KaliGobusterAdapter)
    assert isinstance(adapter.backend, KaliBackend)
    assert not isinstance(adapter.backend, DockerBackend)


def test_get_adapter_legacy_still_routes_to_docker_backend():
    adapter = get_adapter("nmap")
    assert isinstance(adapter.backend, DockerBackend)
    assert not isinstance(adapter.backend, KaliBackend)


def test_palette_for_web_includes_all_three_kali_tools():
    palette = {e.slug for e in palette_for_domain(frozenset({"web", "api"}))}
    assert {"kali_gobuster", "kali_sqlmap", "kali_nikto"} <= palette


def test_capabilities_passthrough_from_registry():
    adapter = KaliSqlmapAdapter(backend=KaliBackend())
    caps = set(adapter.get_capabilities())
    assert caps == {"sqli_detect", "sqli_exploit"}
