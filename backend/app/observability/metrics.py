"""Lightweight Prometheus-style metrics registry (plan v3.2.1 §6).

When the optional ``prometheus_client`` package is installed, counters /
histograms are wired into the global default registry. When it is not,
an in-memory map keeps the same counter semantics so service code and
tests behave identically.

Metric inventory (per plan §0.5):
    osa_session_interview_turns_total{outcome}
    osa_session_ambiguity_score{bucket}
    osa_anthropic_tokens_total{model, phase}
    osa_anthropic_usd_cost_total{model, team_id}
    osa_domain_agent_dispatch_total{domain, result}
    osa_rescope_events_total{action}
    osa_active_recon_targets_total{result}
    osa_session_time_to_ready_for_review_seconds   (histogram, seconds)
    osa_knowledge_load_total{result}                (counter, P5 additional)
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Mapping

try:  # pragma: no cover — exercised when prometheus_client is installed
    from prometheus_client import (
        Counter as _PromCounter,
        Histogram as _PromHistogram,
    )
    _HAS_PROM = True
except Exception:  # noqa: BLE001
    _PromCounter = None
    _PromHistogram = None
    _HAS_PROM = False


_LOCK = threading.Lock()


def _label_key(labels: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
    if not labels:
        return ()
    return tuple(sorted(labels.items()))


class _InMemoryCounter:
    def __init__(self, name: str, label_names: tuple[str, ...]) -> None:
        self.name = name
        self.label_names = label_names
        self._values: dict[tuple, float] = defaultdict(float)

    def inc(self, value: float = 1.0, labels: Mapping[str, str] | None = None) -> None:
        with _LOCK:
            self._values[_label_key(labels)] += value

    def value(self, labels: Mapping[str, str] | None = None) -> float:
        return self._values.get(_label_key(labels), 0.0)

    def snapshot(self) -> dict[tuple, float]:
        with _LOCK:
            return dict(self._values)


class _InMemoryHistogram:
    def __init__(
        self,
        name: str,
        label_names: tuple[str, ...],
        buckets: tuple[float, ...],
    ) -> None:
        self.name = name
        self.label_names = label_names
        self.buckets = buckets
        self._observations: dict[tuple, list[float]] = defaultdict(list)

    def observe(self, value: float, labels: Mapping[str, str] | None = None) -> None:
        with _LOCK:
            self._observations[_label_key(labels)].append(value)

    def observations(self, labels: Mapping[str, str] | None = None) -> list[float]:
        return list(self._observations.get(_label_key(labels), []))


class _CounterFacade:
    def __init__(self, name: str, description: str, label_names: tuple[str, ...]) -> None:
        self._impl = _InMemoryCounter(name, label_names)
        self._prom = None
        if _HAS_PROM:
            self._prom = _PromCounter(name, description, label_names)
        self.label_names = label_names

    def inc(self, value: float = 1.0, **labels: str) -> None:
        self._impl.inc(value, labels)
        if self._prom is not None:
            if labels:
                self._prom.labels(**labels).inc(value)
            else:
                self._prom.inc(value)

    def value(self, **labels: str) -> float:
        return self._impl.value(labels)


class _HistogramFacade:
    def __init__(
        self,
        name: str,
        description: str,
        label_names: tuple[str, ...],
        buckets: tuple[float, ...],
    ) -> None:
        self._impl = _InMemoryHistogram(name, label_names, buckets)
        self._prom = None
        if _HAS_PROM:
            self._prom = _PromHistogram(name, description, label_names, buckets=list(buckets))
        self.label_names = label_names

    def observe(self, value: float, **labels: str) -> None:
        self._impl.observe(value, labels)
        if self._prom is not None:
            if labels:
                self._prom.labels(**labels).observe(value)
            else:
                self._prom.observe(value)

    def observations(self, **labels: str) -> list[float]:
        return self._impl.observations(labels)


class _GaugeFacade:
    """Prometheus-style gauge (current value, can go up or down)."""

    def __init__(self, name: str, description: str, label_names: tuple[str, ...]) -> None:
        self._prom = None
        if _HAS_PROM:
            try:
                from prometheus_client import Gauge as _PromGauge  # noqa: PLC0415
                self._prom = _PromGauge(name, description, label_names)
            except Exception:  # noqa: BLE001
                pass
        self.label_names = label_names
        self._current: dict[tuple, float] = {}

    def set(self, value: float, **labels: str) -> None:
        key = _label_key(labels)
        with _LOCK:
            self._current[key] = value
        if self._prom is not None:
            if labels:
                self._prom.labels(**labels).set(value)
            else:
                self._prom.set(value)

    def value(self, **labels: str) -> float:
        return self._current.get(_label_key(labels), 0.0)


class MetricsRegistry:
    """Single global registry instance (``metrics``)."""

    def __init__(self) -> None:
        self.session_interview_turns_total = _CounterFacade(
            "osa_session_interview_turns_total",
            "Workflow chat turns completed, partitioned by outcome.",
            ("outcome",),
        )
        self.session_ambiguity_score = _CounterFacade(
            "osa_session_ambiguity_score",
            "Distribution of model-self-rated ambiguity scores by bucket.",
            ("bucket",),
        )
        self.anthropic_tokens_total = _CounterFacade(
            "osa_anthropic_tokens_total",
            "Anthropic API tokens consumed.",
            ("model", "phase"),
        )
        self.anthropic_usd_cost_total = _CounterFacade(
            "osa_anthropic_usd_cost_total",
            "Aggregated USD spend on Anthropic API by model and team.",
            ("model", "team_id"),
        )
        self.domain_agent_dispatch_total = _CounterFacade(
            "osa_domain_agent_dispatch_total",
            "Domain-agent dispatch attempts partitioned by domain and result.",
            ("domain", "result"),
        )
        self.rescope_events_total = _CounterFacade(
            "osa_rescope_events_total",
            "Rescope-flow transitions (paused/approved/rejected/auto_drop).",
            ("action",),
        )
        self.active_recon_targets_total = _CounterFacade(
            "osa_active_recon_targets_total",
            "Discovered hosts that entered the rescope flow, by result.",
            ("result",),
        )
        self.session_time_to_ready_for_review_seconds = _HistogramFacade(
            "osa_session_time_to_ready_for_review_seconds",
            "Wall-clock time from session draft creation to ready_for_review state.",
            (),
            (5, 15, 30, 60, 120, 300, 600, 1800),
        )
        self.knowledge_load_total = _CounterFacade(
            "osa_knowledge_load_total",
            "Knowledge-loader invocations partitioned by result.",
            ("result",),
        )
        # ── Kali coexistence (PR-8) — 5 new counters wire into the safety/audit
        # chain and the docker-socket-proxy / Python middleware front line. ──
        self.kali_exec_total = _CounterFacade(
            "osa_kali_exec_total",
            "KaliBackend tool executions partitioned by slug and outcome.",
            ("tool_slug", "outcome"),
        )
        self.kali_shim_block_total = _CounterFacade(
            "osa_kali_shim_block_total",
            "WhitelistShim rejections partitioned by deny reason.",
            ("reason",),
        )
        self.kali_container_start_failures_total = _CounterFacade(
            "osa_kali_container_start_failures_total",
            "KaliBackend.start container creation failures partitioned by reason.",
            ("reason",),
        )
        self.kali_socket_proxy_403_total = _CounterFacade(
            "osa_kali_socket_proxy_403_total",
            "docker-socket-proxy 403 responses partitioned by endpoint.",
            ("endpoint",),
        )
        self.kali_filter_plan_block_total = _CounterFacade(
            "osa_kali_filter_plan_block_total",
            "Steps dropped by filter_plan_steps kali_* branch.",
            ("tool_slug", "reason"),
        )
        # ── Multi-provider LLM + budget guard (PR1.5) ────────────────────────
        self.llm_tokens_total = _CounterFacade(
            "osa_llm_tokens_total",
            "LLM tokens consumed by provider, model, and kind (prompt|completion).",
            ("provider", "model", "kind"),
        )
        self.llm_cost_usd_total = _CounterFacade(
            "osa_llm_cost_usd_total",
            "USD cost incurred by provider and model.",
            ("provider", "model"),
        )
        self.budget_guard_layer_a_block_total = _CounterFacade(
            "osa_budget_guard_layer_a_block_total",
            "Pre-spawn aggregate budget guard blocks.",
            ("reason",),
        )
        self.budget_guard_layer_b_block_total = _CounterFacade(
            "osa_budget_guard_layer_b_block_total",
            "Per-task pre-call budget guard blocks.",
            ("reason",),
        )
        self.budget_guard_estimator_drift = _GaugeFacade(
            "osa_budget_guard_estimator_drift",
            "Rolling 24h actual/estimated cost ratio per provider.",
            ("provider",),
        )
        # ── W4/PR4.4 — per-family token budget and per-layer scrubber counters ──
        self.family_tokens_total = _CounterFacade(
            "osa_family_tokens_total",
            "Total LLM tokens consumed per family per session",
            ("session_id", "family_kind"),
        )
        self.conversation_scrubber_hits_total = _CounterFacade(
            "osa_conversation_scrubber_hits_total",
            "Scrubber layer-hit count by layer",
            ("layer",),
        )
        self.conversation_scrubber_circuit_open_total = _CounterFacade(
            "osa_conversation_scrubber_circuit_open_total",
            "Number of times the L4 token-bucket circuit opened",
            ("session_id",),
        )
        self.conversation_topic_dropped_events_total = _CounterFacade(
            "osa_conversation_topic_dropped_events_total",
            "Events dropped by the per-session rate limiter",
            ("session_id", "topic"),
        )


metrics = MetricsRegistry()


# Module-level aliases so other modules can import these counters directly.
family_tokens_total = metrics.family_tokens_total
conversation_scrubber_hits_total = metrics.conversation_scrubber_hits_total
conversation_scrubber_circuit_open_total = metrics.conversation_scrubber_circuit_open_total
conversation_topic_dropped_events_total = metrics.conversation_topic_dropped_events_total


def ambiguity_bucket(score: float) -> str:
    """Quantize an ambiguity score into a histogram bucket label."""
    if score < 0.2:
        return "0.0-0.2"
    if score < 0.4:
        return "0.2-0.4"
    if score < 0.6:
        return "0.4-0.6"
    if score < 0.8:
        return "0.6-0.8"
    return "0.8-1.0"
