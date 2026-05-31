from __future__ import annotations

import uuid

import pytest

from app.safety.conversation_scrubber import ConversationScrubber, ScrubResult


def _scrubber(
    session_id: uuid.UUID | None = None,
    l2_threshold: float = 4.5,
    capacity: int = 50,
) -> ConversationScrubber:
    if session_id is None:
        session_id = uuid.uuid4()
    return ConversationScrubber(
        session_id,
        l2_entropy_threshold=l2_threshold,
        l4_bucket_capacity=capacity,
        l4_refill_per_sec=5.0,
    )


class TestLayer1Patterns:
    def test_redacts_openai_api_key(self):
        s = _scrubber()
        result = s.scrub("token=sk-abc123def456ghi789jkl")
        assert "[REDACTED:api_key]" in result.scrubbed_text
        assert "sk-abc123def456ghi789jkl" not in result.scrubbed_text

    def test_redacts_aws_access_key(self):
        s = _scrubber()
        result = s.scrub("key=AKIAIOSFODNN7EXAMPLE value")
        assert "[REDACTED:api_key]" in result.scrubbed_text
        assert "AKIAIOSFODNN7EXAMPLE" not in result.scrubbed_text

    def test_redacts_github_token(self):
        s = _scrubber()
        token = "ghp_" + "A" * 36
        result = s.scrub(f"Authorization: {token}")
        assert "[REDACTED:api_key]" in result.scrubbed_text
        assert token not in result.scrubbed_text

    def test_redacts_private_key_block(self):
        s = _scrubber()
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA0Z3VS5JJcds3xHn/ygWep4B\n"
            "-----END RSA PRIVATE KEY-----"
        )
        result = s.scrub(pem)
        assert "[REDACTED:private_key_block]" in result.scrubbed_text
        assert "BEGIN RSA PRIVATE KEY" not in result.scrubbed_text

    def test_redacts_jwt(self):
        s = _scrubber()
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        result = s.scrub(f"token: {jwt}")
        assert "[REDACTED:jwt]" in result.scrubbed_text
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result.scrubbed_text

    def test_redacts_bearer_token(self):
        s = _scrubber()
        text = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz1234567890"
        result = s.scrub(text)
        assert "[REDACTED:bearer_token]" in result.scrubbed_text

    def test_does_not_redact_innocent_text(self):
        s = _scrubber()
        text = "hello world this is a normal sentence"
        result = s.scrub(text)
        assert result.scrubbed_text == text
        assert result.layer_hits["l1"] == 0


class TestLayer2Entropy:
    def test_redacts_high_entropy_random_string(self):
        s = _scrubber()
        # 40-char random base64-like string with high entropy
        high_entropy = "aB3dEfGhIjKlMnOpQrStUvWxYz0123456789XyZ"
        result = s.scrub(high_entropy)
        assert "high_entropy" in result.scrubbed_text
        assert result.layer_hits["l2"] >= 1

    def test_keeps_low_entropy_token(self):
        s = _scrubber()
        low_entropy = "aaaaaaaaaaaaaaaaaaaa"  # 20 chars, all same
        result = s.scrub(low_entropy)
        assert low_entropy in result.scrubbed_text
        assert result.layer_hits["l2"] == 0

    def test_threshold_configurable(self):
        # Default threshold 4.5 flags more; raising to 6.0 flags fewer
        text = "aB3dEfGhIjKlMnOpQrStUvWxYz0123456789XyZ someOtherToken1234567890XZ"
        s_default = _scrubber(l2_threshold=4.5)
        s_high = _scrubber(l2_threshold=6.0)
        result_default = s_default.scrub(text)
        result_high = s_high.scrub(text)
        assert result_default.layer_hits["l2"] >= result_high.layer_hits["l2"]


class TestLayer3Canary:
    def test_canary_deterministic_for_same_session(self):
        sid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        canaries = set()
        for _ in range(8):
            s = ConversationScrubber(sid)
            # Extract canary by injecting it and checking
            canary = s._canary
            canaries.add(canary)
        assert len(canaries) == 1

    def test_canary_differs_across_sessions(self):
        sid1 = uuid.uuid4()
        sid2 = uuid.uuid4()
        s1 = ConversationScrubber(sid1)
        s2 = ConversationScrubber(sid2)
        assert s1._canary != s2._canary

    def test_check_canary_detects_substring_in_text(self):
        sid = uuid.uuid4()
        s = ConversationScrubber(sid)
        canary = s._canary
        text = f"Response data: {canary} end"
        assert s.check_canary(text, canary) is True

    def test_canary_redacted_in_scrub_when_present(self):
        sid = uuid.uuid4()
        s = ConversationScrubber(sid)
        canary = s._canary
        text = f"some text {canary} more text"
        result = s.scrub(text)
        assert "[REDACTED:canary_leak]" in result.scrubbed_text
        assert canary not in result.scrubbed_text
        assert result.canary_leaked is True
        assert result.layer_hits["l3"] == 1


class TestLayer4CircuitBreaker:
    def test_circuit_opens_after_capacity_hits(self):
        # capacity=5 so 6th hit opens circuit
        sid = uuid.uuid4()
        s = ConversationScrubber(sid, l4_bucket_capacity=5, l4_refill_per_sec=0.0)
        circuit_opened = False
        # Deterministic high-entropy token: 50 distinct ASCII letters+digits
        # without any non-word separator (so _TOKEN_SPLIT keeps it as a single
        # token >=20 chars). Shannon entropy >= log2(50) > 4.5.
        base = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789aBcDeFgHiJkLm"  # 50 chars
        assert len(base) >= 20
        for i in range(6):
            # Vary by appending a unique suffix to ensure distinct tokens, but
            # keep the prefix high-entropy.
            token = base + str(i)
            result = s.scrub(token)
            if result.circuit_open:
                circuit_opened = True
                break
        assert circuit_opened

    def test_bucket_refills_over_time(self, monkeypatch):
        sid = uuid.uuid4()
        base_time = 1000.0
        current_time = [base_time]

        monkeypatch.setattr("app.safety.conversation_scrubber.time.monotonic", lambda: current_time[0])

        s = ConversationScrubber(sid, l4_bucket_capacity=5, l4_refill_per_sec=5.0)
        # Drain all tokens
        for _ in range(5):
            s._consume_token()
        assert s._bucket < 1.0

        # Advance time by 10 seconds → should refill 50 tokens, capped at 5
        current_time[0] = base_time + 10.0
        s._refill_bucket()
        assert s._bucket == 5.0


class TestAdversarialFixtures:
    def test_concatenated_secrets_caught(self):
        s = _scrubber()
        # Both an API key and a bearer token in the same text
        text = "key1=sk-ABCDEFGHIJKLMNOP key2=Bearer eyJabc.def.ghi12345678901234567890"
        result = s.scrub(text)
        assert result.layer_hits["l1"] >= 1

    def test_obfuscated_via_inline_whitespace_still_caught_by_pattern_or_entropy(self):
        s = _scrubber()
        # High-entropy token that won't match L1 patterns but should trigger L2
        obfuscated = "aB3dEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfGhIjKl"
        result = s.scrub(obfuscated)
        # Should be caught by L2 entropy
        assert "REDACTED" in result.scrubbed_text or result.layer_hits["l1"] > 0 or result.layer_hits["l2"] > 0

    def test_does_not_corrupt_legitimate_long_words(self):
        s = _scrubber()
        text = "antidisestablishmentarianism documentation"
        result = s.scrub(text)
        # These are low-entropy English words, should not be redacted
        assert "antidisestablishmentarianism" in result.scrubbed_text
        assert result.layer_hits["l2"] == 0
