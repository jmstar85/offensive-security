"""Tests that ConversationScrubber increments metrics on layer hits — W4/PR4.4."""
from __future__ import annotations

import uuid

from app.observability.metrics import metrics
from app.safety.conversation_scrubber import ConversationScrubber


def _hits_counter(layer: str) -> float:
    return metrics.conversation_scrubber_hits_total.value(layer=layer)


def _circuit_counter(session_id: uuid.UUID) -> float:
    return metrics.conversation_scrubber_circuit_open_total.value(session_id=str(session_id))


def test_l1_hit_increments_metric():
    sid = uuid.uuid4()
    scrubber = ConversationScrubber(sid)
    before = _hits_counter("l1")
    scrubber.scrub("token=sk-ABCDEFGHIJKLMNOPQRST")
    after = _hits_counter("l1")
    assert after > before


def test_l2_hit_increments_metric():
    sid = uuid.uuid4()
    scrubber = ConversationScrubber(sid, l2_entropy_threshold=4.5)
    before = _hits_counter("l2")
    # 50-char mixed-case alphanumeric — high entropy, no L1 pattern match
    high_entropy = "aB3dEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfGhIjKlmN"
    scrubber.scrub(high_entropy)
    after = _hits_counter("l2")
    assert after > before


def test_circuit_open_increments_metric():
    sid = uuid.uuid4()
    # capacity=1, refill=0 so second scrub call that hits L1 drains the bucket
    scrubber = ConversationScrubber(sid, l4_bucket_capacity=1, l4_refill_per_sec=0.0)
    before = _circuit_counter(sid)
    # First call consumes the single token
    scrubber.scrub("token=sk-ABCDEFGHIJKLMNOPQRST")
    # Second call: bucket is empty → circuit_open=True
    scrubber.scrub("token=sk-ABCDEFGHIJKLMNOPQRST")
    after = _circuit_counter(sid)
    assert after > before


def test_no_hit_does_not_increment():
    sid = uuid.uuid4()
    scrubber = ConversationScrubber(sid)
    before_l1 = _hits_counter("l1")
    before_l2 = _hits_counter("l2")
    before_l3 = _hits_counter("l3")
    scrubber.scrub("hello world")
    assert _hits_counter("l1") == before_l1
    assert _hits_counter("l2") == before_l2
    assert _hits_counter("l3") == before_l3
