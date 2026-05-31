import os
import time
import httpx
import pytest

DVWA = os.environ.get("OSA_E2E_DVWA_URL", "")
JUICE = os.environ.get("OSA_E2E_JUICE_URL", "")
BACKEND = os.environ.get("OSA_E2E_BACKEND_URL", "http://localhost:8000")
TIMEOUT_S = int(os.environ.get("OSA_E2E_TIMEOUT_S", "300"))

def _client():
    return httpx.Client(base_url=BACKEND, timeout=30.0)

def _start_session(client, target_url: str, prompt: str) -> str:
    proj = client.post("/api/v1/projects", json={
        "name": f"e2e-{int(time.time())}",
        "description": "vector e2e",
        "targets": {"domains": [target_url], "ip_ranges": []},
    })
    proj.raise_for_status()
    pid = proj.json()["id"]
    sess = client.post("/api/v1/pentest-sessions/start", json={
        "project_id": pid, "prompt": prompt,
    })
    sess.raise_for_status()
    return sess.json()["id"]

def _wait_for_completion(client, sid: str) -> dict:
    deadline = time.time() + TIMEOUT_S
    while time.time() < deadline:
        r = client.get(f"/api/v1/pentest-sessions/{sid}")
        r.raise_for_status()
        status = r.json().get("status")
        if status in {"completed", "failed", "killed"}:
            return r.json()
        time.sleep(2)
    raise TimeoutError(f"session {sid} did not complete in {TIMEOUT_S}s")

def _findings(client, sid: str) -> list[dict]:
    r = client.get(f"/api/v1/pentest-sessions/{sid}/findings")
    r.raise_for_status()
    return r.json().get("findings", [])

def _audit_for_session(client, sid: str) -> list[dict]:
    r = client.get(f"/api/v1/audit-logs?session_id={sid}")
    r.raise_for_status()
    return r.json().get("rows", [])


class TestXSSVector:
    def test_xss_against_dvwa(self):
        with _client() as c:
            sid = _start_session(c, DVWA, "Find reflected and DOM XSS on this target")
            _wait_for_completion(c, sid)
            findings = _findings(c, sid)
            assert any(f.get("type") == "dom_xss_probe" for f in findings)
            assert any(a.get("action", "").startswith("session_") for a in _audit_for_session(c, sid))

    def test_xss_against_juice_shop(self):
        with _client() as c:
            sid = _start_session(c, JUICE, "Find reflected and DOM XSS")
            _wait_for_completion(c, sid)
            findings = _findings(c, sid)
            assert any(f.get("type") == "dom_xss_probe" for f in findings)


class TestSQLiVector:
    def test_sqli_against_dvwa(self):
        with _client() as c:
            sid = _start_session(c, DVWA, "Probe SQL injection on form params")
            _wait_for_completion(c, sid)
            findings = _findings(c, sid)
            # sqlmap parser emits a sqli_finding type when present.
            assert any("sqli" in (f.get("type") or "").lower() for f in findings)


class TestCSRFVector:
    def test_csrf_against_dvwa(self):
        with _client() as c:
            sid = _start_session(c, DVWA, "Check for CSRF on state-changing endpoints")
            _wait_for_completion(c, sid)
            findings = _findings(c, sid)
            assert any(f.get("type") == "csrf_form_replay" for f in findings)


class TestSSRFVector:
    def test_ssrf_against_juice_shop(self):
        with _client() as c:
            sid = _start_session(c, JUICE, "Look for SSRF — out-of-band correlation via interactsh")
            _wait_for_completion(c, sid)
            findings = _findings(c, sid)
            # SSRF detection correlates an outbound finding with an
            # oob_callback row via correlation_id.
            oobs = [f for f in findings if f.get("type") == "oob_callback"]
            correlated = [f for f in findings if f.get("correlation_id") and any(o.get("correlation_id") == f.get("correlation_id") for o in oobs)]
            assert oobs or correlated  # at least one OOB callback OR a correlation row


class TestIDORVector:
    def test_idor_against_juice_shop(self):
        with _client() as c:
            sid = _start_session(c, JUICE, "Check for IDOR — increment object IDs and watch for unauthorised reads")
            _wait_for_completion(c, sid)
            findings = _findings(c, sid)
            assert any(("idor" in (f.get("type") or "").lower()) or ("auth" in (f.get("severity") or "").lower()) for f in findings)


class TestCMDIVector:
    def test_cmdi_against_dvwa(self):
        with _client() as c:
            sid = _start_session(c, DVWA, "Probe command-injection on shell-style params")
            _wait_for_completion(c, sid)
            findings = _findings(c, sid)
            # commix parser emits 'command_injection'
            assert any(f.get("type") == "command_injection" for f in findings)
