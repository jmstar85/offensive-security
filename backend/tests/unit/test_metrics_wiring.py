"""PR-8 — metrics registration + audit event schema invariants."""
from __future__ import annotations

from app.observability.metrics import metrics
from app.safety.audit import KALI_AUDIT_EVENT_SCHEMAS, emit_kali_metric
from app.safety.kali_allowlist import audit_safety_event


def test_kali_counters_are_registered():
    expected = {
        "kali_exec_total",
        "kali_shim_block_total",
        "kali_container_start_failures_total",
        "kali_socket_proxy_403_total",
        "kali_filter_plan_block_total",
    }
    for attr in expected:
        counter = getattr(metrics, attr, None)
        assert counter is not None, f"metrics.{attr} not registered"


def test_kali_audit_event_schemas_complete():
    assert set(KALI_AUDIT_EVENT_SCHEMAS) == {
        "kali_exec.start",
        "kali_exec.shim_block",
        "kali_exec.hardening_violation",
        "kali_exec.filter_plan_steps_block",
        "kali_exec.tier_gate_block",
    }
    common = {"tool_slug", "args", "reason", "step_id", "session_id", "timestamp"}
    for event, fields in KALI_AUDIT_EVENT_SCHEMAS.items():
        assert common <= fields, f"{event} missing common fields"


def test_emit_kali_metric_bumps_shim_block_counter():
    before = metrics.kali_shim_block_total.value(reason="deny_flag:--os-shell")
    emit_kali_metric("kali_exec.shim_block", {"reason": "deny_flag:--os-shell"})
    after = metrics.kali_shim_block_total.value(reason="deny_flag:--os-shell")
    assert after == before + 1


def test_emit_kali_metric_bumps_filter_plan_block_counter():
    labels = {"tool_slug": "sqlmap", "reason": "deny_flag:--os-shell"}
    before = metrics.kali_filter_plan_block_total.value(**labels)
    emit_kali_metric(
        "kali_exec.filter_plan_steps_block",
        {"slug": "sqlmap", "reason": "deny_flag:--os-shell"},
    )
    after = metrics.kali_filter_plan_block_total.value(**labels)
    assert after == before + 1


def test_emit_kali_metric_bumps_exec_total_on_start():
    before = metrics.kali_exec_total.value(tool_slug="gobuster", outcome="started")
    emit_kali_metric("kali_exec.start", {"tool_slug": "gobuster"})
    after = metrics.kali_exec_total.value(tool_slug="gobuster", outcome="started")
    assert after == before + 1


def test_emit_kali_metric_bumps_container_start_failures():
    before = metrics.kali_container_start_failures_total.value(reason="image_pull")
    emit_kali_metric("kali_exec.hardening_violation", {"reason": "image_pull"})
    after = metrics.kali_container_start_failures_total.value(reason="image_pull")
    assert after == before + 1


def test_audit_safety_event_drives_metric_through_kali_allowlist():
    # End-to-end: kali_allowlist.audit_safety_event must bump the metric via
    # emit_kali_metric without the caller knowing about the chain.
    before = metrics.kali_shim_block_total.value(reason="path_deny_prefix:/etc/")
    audit_safety_event(
        "kali_exec.shim_block",
        {"slug": "gobuster", "args": ["dir", "--wordlist=/etc/shadow"],
         "reason": "path_deny_prefix:/etc/"},
    )
    after = metrics.kali_shim_block_total.value(reason="path_deny_prefix:/etc/")
    assert after == before + 1


def test_emit_kali_metric_ignores_unknown_events():
    # Unknown event types are no-ops — never raise.
    emit_kali_metric("kali_exec.something_unknown", {"reason": "x"})
