"""Load harness — SF-CRITIC-1 v1.1.

Run with:
  locust -f backend/tests/_load/multi_user_load_harness.py \
    --host http://localhost:8000 --users 100 --spawn-rate 10 --run-time 60s \
    --headless --csv backend/.omc/state/load-run
"""
from __future__ import annotations
import json
import os
import time
import uuid
from locust import HttpUser, task, between, events  # noqa: F401

LOAD_HARNESS_VERSION = "1.0-w2b"

API_PREFIX = os.environ.get("OSA_API_PREFIX", "/api/v1")


class OsaMultiUser(HttpUser):
    wait_time = between(0.2, 0.8)
    _user_email_template = "loaduser+{idx}@example.test"

    def on_start(self) -> None:
        self.user_idx = uuid.uuid4().int % 10_000
        email = self._user_email_template.format(idx=self.user_idx)
        r = self.client.post(f"{API_PREFIX}/auth/login", json={"email": email, "password": "loadtest-pw"}, name="auth/login")
        if r.status_code in (401, 404):
            self.client.post(f"{API_PREFIX}/auth/register", json={
                "email": email, "password": "loadtest-pw", "full_name": f"Load User {self.user_idx}"
            }, name="auth/register")
            r = self.client.post(f"{API_PREFIX}/auth/login", json={"email": email, "password": "loadtest-pw"}, name="auth/login")
        tok = r.json().get("access_token") if r.ok else None
        self.client.headers.update({"Authorization": f"Bearer {tok}"} if tok else {})

    @task(3)
    def start_pentest_session(self) -> None:
        t0 = time.monotonic()
        project_r = self.client.post(f"{API_PREFIX}/projects", json={
            "name": f"load-project-{self.user_idx}-{int(time.time())}",
            "description": "load test",
            "targets": {"domains": ["example.test"], "ip_ranges": []},
        }, name="projects/create")
        if not project_r.ok:
            return
        pid = project_r.json().get("id")
        sess_r = self.client.post(f"{API_PREFIX}/pentest-sessions/start", json={
            "project_id": pid,
            "prompt": f"locust scenario {self.user_idx}",
        }, name="sessions/start")
        latency = time.monotonic() - t0
        events.request.fire(
            request_type="locust",
            name="end_to_end_session_start",
            response_time=latency * 1000,
            response_length=0,
            exception=None if sess_r.ok else Exception(f"status={sess_r.status_code}"),
            context={},
        )

    @task(1)
    def list_audit_logs(self) -> None:
        self.client.get(f"{API_PREFIX}/audit-logs?limit=50", name="audit-logs/list")
