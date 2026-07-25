"""(c) New OWASP web tools: katana (crawler/surface discovery) + OWASP ZAP
(canonical DAST baseline). Both tier=active_recon, gated behind approved_active_recon."""
from __future__ import annotations

from unittest.mock import MagicMock

from app.agents.katana import KatanaAdapter
from app.agents.zap import ZapAdapter
from app.agents.registry import get_adapter, get_tool_entry, list_agent_types


def test_both_registered_at_active_recon():
    for slug in ("katana", "zap"):
        assert slug in list_agent_types()
        assert get_tool_entry(slug).tier == "active_recon"  # gated by approved_active_recon
        assert get_tool_entry(slug).description  # registration tests require a description
    # resolvable via the docker backend
    assert type(get_adapter("katana")).__name__ == "KatanaAdapter"
    assert type(get_adapter("zap")).__name__ == "ZapAdapter"


def test_katana_builds_bounded_crawl_to_stdout():
    cmd = KatanaAdapter(backend=MagicMock()).build_command(
        {"domains": ["scanme.nmap.org"], "ip_ranges": []}, {}
    )
    assert "-u" in cmd and "https://scanme.nmap.org" in cmd
    assert "-jsonl" in cmd  # findings to stdout
    assert "-d" in cmd and "-timeout" in cmd  # bounded
    # in-scope crawl only, or the EgressMonitor hard-halts the run on off-site links
    assert cmd[cmd.index("-fs") + 1] == "fqdn"


def test_katana_parses_json_and_plain_urls():
    r = KatanaAdapter(backend=MagicMock()).parse_output(
        '{"url":"https://x/a"}\n{"request":{"endpoint":"https://x/b"}}\nhttps://x/c\nnoise'
    )
    urls = [f["url"] for f in r.findings]
    assert urls == ["https://x/a", "https://x/b", "https://x/c"]


def test_zap_parses_warn_and_fail_lines():
    r = ZapAdapter(backend=MagicMock()).parse_output(
        "WARN-NEW: Content Security Policy (CSP) Header Not Set [10038] x 3\n"
        "FAIL-NEW: SQL Injection [40018]\n"
        "PASS: Cookie Secure Flag"
    )
    names = {f["name"]: f["severity"] for f in r.findings}
    assert names["Content Security Policy (CSP) Header Not Set"] == "medium"
    assert names["SQL Injection"] == "high"
    assert "Cookie Secure Flag" not in names  # PASS lines are not findings


def test_zap_builds_bounded_baseline():
    cmd = ZapAdapter(backend=MagicMock()).build_command(
        {"domains": ["scanme.nmap.org"], "ip_ranges": []}, {}
    )
    assert cmd[:2] == ["-t", "https://scanme.nmap.org"]
    assert "-m" in cmd  # bounded spider minutes
