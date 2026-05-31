from __future__ import annotations

import hashlib
import math
import re
import time
import uuid
from dataclasses import dataclass, field

from app.observability.metrics import (
    conversation_scrubber_circuit_open_total,
    conversation_scrubber_hits_total,
)


@dataclass
class ScrubResult:
    scrubbed_text: str
    layer_hits: dict[str, int]
    circuit_open: bool = False
    canary_leaked: bool = False


_L1_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "api_key",
        re.compile(
            r"\b(sk-[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16}|gh[ps]_[A-Za-z0-9_]{36}|xox[abps]-[0-9A-Za-z-]+)"
        ),
    ),
    (
        "private_key_block",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH |DSA |)?PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    ),
    (
        "bearer_token",
        re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}"),
    ),
    (
        "basic_auth",
        re.compile(r"\bBasic\s+[A-Za-z0-9+/=]{12,}"),
    ),
    (
        "email_password_pair",
        re.compile(r"\bpassword[=:\s]+[^\s]{6,}", re.IGNORECASE),
    ),
]

_TOKEN_SPLIT = re.compile(r"[\s\W]+")


def _shannon_entropy(token: str) -> float:
    if not token:
        return 0.0
    freq: dict[str, int] = {}
    for ch in token:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(token)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def _derive_canary(session_id: uuid.UUID) -> str:
    digest = hashlib.sha256(session_id.bytes + b"canary-v1").hexdigest()
    return digest[:16]


class ConversationScrubber:
    def __init__(
        self,
        session_id: uuid.UUID,
        *,
        l2_entropy_threshold: float = 4.5,
        l4_bucket_capacity: int = 50,
        l4_refill_per_sec: float = 5.0,
    ) -> None:
        self._session_id = session_id
        self._l2_threshold = l2_entropy_threshold
        self._l4_capacity = l4_bucket_capacity
        self._l4_refill = l4_refill_per_sec
        self._canary = _derive_canary(session_id)

        self._bucket: float = float(l4_bucket_capacity)
        self._last_refill: float = time.monotonic()

    def _refill_bucket(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._bucket = min(
            float(self._l4_capacity),
            self._bucket + elapsed * self._l4_refill,
        )
        self._last_refill = now

    def _consume_token(self) -> bool:
        """Return True if a token was consumed; False if bucket was empty."""
        self._refill_bucket()
        if self._bucket >= 1.0:
            self._bucket -= 1.0
            return True
        return False

    def scrub(self, text: str) -> ScrubResult:
        hits: dict[str, int] = {"l1": 0, "l2": 0, "l3": 0}
        circuit_open = False
        canary_leaked = False

        # Layer 1: pattern scrub
        result = text
        for kind, pattern in _L1_PATTERNS:
            def _replace(m: re.Match[str], kind: str = kind) -> str:
                return f"[REDACTED:{kind}]"

            new_result, count = pattern.subn(_replace, result)
            if count:
                hits["l1"] += count
                conversation_scrubber_hits_total.inc(float(count), layer="l1")
                for _ in range(count):
                    if not self._consume_token():
                        circuit_open = True
                result = new_result

        # Layer 2: Shannon entropy scrub (per token)
        tokens = _TOKEN_SPLIT.split(result)
        for token in tokens:
            if len(token) >= 20:
                entropy = _shannon_entropy(token)
                if entropy >= self._l2_threshold:
                    hits["l2"] += 1
                    conversation_scrubber_hits_total.inc(1.0, layer="l2")
                    if not self._consume_token():
                        circuit_open = True
                    result = result.replace(
                        token, f"[REDACTED:high_entropy_{len(token)}]", 1
                    )

        # Layer 3: canary check
        if self._canary in result:
            hits["l3"] += 1
            conversation_scrubber_hits_total.inc(1.0, layer="l3")
            canary_leaked = True
            if not self._consume_token():
                circuit_open = True
            result = result.replace(self._canary, "[REDACTED:canary_leak]")

        if circuit_open:
            conversation_scrubber_circuit_open_total.inc(1.0, session_id=str(self._session_id))

        return ScrubResult(
            scrubbed_text=result,
            layer_hits=hits,
            circuit_open=circuit_open,
            canary_leaked=canary_leaked,
        )

    def check_canary(self, text: str, canary: str) -> bool:
        return canary in text
