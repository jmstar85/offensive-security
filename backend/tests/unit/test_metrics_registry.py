"""Plan v3.2.1 §6 — metrics registry semantics + ambiguity bucket quantization."""
from __future__ import annotations

import pytest

from app.observability.metrics import ambiguity_bucket, metrics


def test_metrics_registry_exposes_all_required_counters():
    required = {
        "session_interview_turns_total",
        "session_ambiguity_score",
        "anthropic_tokens_total",
        "anthropic_usd_cost_total",
        "domain_agent_dispatch_total",
        "rescope_events_total",
        "active_recon_targets_total",
        "session_time_to_ready_for_review_seconds",
        "knowledge_load_total",
    }
    for attr in required:
        assert hasattr(metrics, attr), attr


def test_counter_inc_accumulates_value():
    before = metrics.rescope_events_total.value(action="paused-test-isolated")
    metrics.rescope_events_total.inc(action="paused-test-isolated")
    metrics.rescope_events_total.inc(action="paused-test-isolated")
    after = metrics.rescope_events_total.value(action="paused-test-isolated")
    assert after - before == 2


def test_counter_label_isolation():
    metrics.domain_agent_dispatch_total.inc(domain="x-test", result="ready_for_review")
    metrics.domain_agent_dispatch_total.inc(domain="x-test", result="interviewing")
    assert metrics.domain_agent_dispatch_total.value(domain="x-test", result="ready_for_review") >= 1
    assert metrics.domain_agent_dispatch_total.value(domain="x-test", result="interviewing") >= 1
    # different label combo isolated
    assert metrics.domain_agent_dispatch_total.value(domain="never-set", result="ready_for_review") == 0


def test_histogram_observe_records_value():
    metrics.session_time_to_ready_for_review_seconds.observe(42.0)
    obs = metrics.session_time_to_ready_for_review_seconds.observations()
    assert 42.0 in obs


@pytest.mark.parametrize(
    "score, bucket",
    [
        (0.0, "0.0-0.2"),
        (0.19, "0.0-0.2"),
        (0.2, "0.2-0.4"),
        (0.39, "0.2-0.4"),
        (0.4, "0.4-0.6"),
        (0.59, "0.4-0.6"),
        (0.6, "0.6-0.8"),
        (0.79, "0.6-0.8"),
        (0.8, "0.8-1.0"),
        (1.0, "0.8-1.0"),
    ],
)
def test_ambiguity_bucket_quantization(score, bucket):
    assert ambiguity_bucket(score) == bucket
