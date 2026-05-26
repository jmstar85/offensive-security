"""v1.1-#3 — KaliExecAdapter reproducibility floor (AC A3.3).

The full A3.3 contract asks that the same
``(KALI_DIGEST, apt-snapshot-date, fixture-target-digest)`` triple
produces deepEqual finding JSON across two end-to-end runs. The
deepEqual claim has two layers:

  1. Deterministic adapter behavior — given the same raw stdout, the
     parser plugin returns the same ``AgentResult.findings`` list, and
     ``KaliExecAdapter.build_command`` produces the same command vector
     from the same target/config.
  2. Deterministic upstream binary — running the pinned binary against
     the pinned fixture image produces the same raw stdout. (1) is
     verified here; (2) is staging-soak territory because it needs a
     real docker daemon + the built osa-kali image + a pinned vulnerable
     fixture, and is documented in
     docs/runbooks/kali-backend.md (A5.6 staging thresholds).

This file is the floor: it pins layer (1) so the adapter never becomes
the source of non-determinism. When the docker-marked staging job lands
in CI, the *same* fixture stdout from a real run should still satisfy
these assertions.
"""
from __future__ import annotations

import pytest

from app.agents.backends.kali import KaliBackend
from app.agents.kali_exec import (
    KaliGobusterAdapter,
    KaliNiktoAdapter,
    KaliSqlmapAdapter,
)
from app.agents.parsers.gobuster import parse as parse_gobuster
from app.agents.parsers.nikto import parse as parse_nikto
from app.agents.parsers.sqlmap import parse as parse_sqlmap


GOBUSTER_FIXTURE = """\
===============================================================
Gobuster v3.6
===============================================================
/admin                (Status: 200) [Size: 1234]
/login.php            (Status: 302) [Size: 0]
/private              (Status: 403) [Size: 287]
"""

SQLMAP_FIXTURE = """\
sqlmap identified the following injection point(s) with a total of N HTTP(s) requests:
---
Parameter: id (GET)
    Type: boolean-based blind
    Title: AND boolean-based blind - WHERE or HAVING clause
    Payload: id=1 AND 1=1
---
"""

NIKTO_FIXTURE = """[
  {"host":"target","vulnerabilities":[
    {"id":"OSVDB-3092","msg":"/admin: This might be interesting"},
    {"id":"OSVDB-3268","msg":"Directory indexing found"}
  ]}
]"""


# --- Parser-layer determinism -------------------------------------------------

@pytest.mark.parametrize("parser,fixture", [
    (parse_gobuster, GOBUSTER_FIXTURE),
    (parse_sqlmap, SQLMAP_FIXTURE),
    (parse_nikto, NIKTO_FIXTURE),
])
def test_parser_is_deterministic_across_runs(parser, fixture):
    """A second pass over the same raw_output produces the same findings."""
    r1 = parser(fixture)
    r2 = parser(fixture)
    assert r1.findings == r2.findings
    assert r1.success == r2.success
    # raw_output round-trips unchanged so downstream diffs on the e2e job
    # only see semantic changes, not whitespace noise.
    assert r1.raw_output == fixture
    assert r2.raw_output == fixture


# --- Adapter-layer determinism -----------------------------------------------

@pytest.mark.parametrize("adapter_cls,slug,args", [
    (KaliGobusterAdapter, "gobuster",
     ["dir", "-u", "http://target/", "-w", "/wordlists/c.txt"]),
    (KaliSqlmapAdapter, "sqlmap",
     ["-u", "http://target/q?id=1", "--batch"]),
    (KaliNiktoAdapter, "nikto",
     ["-h", "http://target/", "-Format", "json"]),
])
def test_build_command_is_deterministic(adapter_cls, slug, args):
    """The command vector depends only on (binary, args). Two calls with
    identical inputs return identical lists."""
    adapter = adapter_cls(backend=KaliBackend())
    cfg = {"tool_slug": slug, "args": args}
    cmd1 = adapter.build_command({}, cfg)
    cmd2 = adapter.build_command({}, cfg)
    assert cmd1 == cmd2


# --- Combined: parse∘build forms a deterministic step result ----------------

def test_combined_pipeline_finding_set_is_deterministic():
    """Stage two: adapter builds command, runs upstream (stubbed by the
    fixture stdout), parser emits findings. Run the same recipe twice and
    the finding set is identical."""
    adapter = KaliGobusterAdapter(backend=KaliBackend())
    cfg = {
        "tool_slug": "gobuster",
        "args": ["dir", "-u", "http://target/", "-w", "/wordlists/c.txt"],
    }

    def run_once():
        cmd = adapter.build_command({}, cfg)
        result = adapter.parse_output(GOBUSTER_FIXTURE)
        return cmd, result.findings

    cmd1, f1 = run_once()
    cmd2, f2 = run_once()
    assert cmd1 == cmd2
    assert f1 == f2


# --- Staging e2e placeholder (docker-marked, skipped here) ------------------

@pytest.mark.skip(
    reason="A3.3 docker e2e lands in the staging-soak CI job — requires "
           "docker daemon + built osa-kali image + pinned vulnerables/web-dvwa "
           "fixture. Tracked in docs/runbooks/kali-backend.md (A5.6)."
)
def test_real_docker_run_is_deterministic_against_pinned_fixture():
    """Two real docker runs of osa-kali against the pinned web-dvwa fixture
    emit deepEqual finding JSON. Implementation deferred to the staging job."""
