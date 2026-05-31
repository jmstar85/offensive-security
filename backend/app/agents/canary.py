"""Per-session canary HMAC for OOB correlation.

Each session derives a canary token via HMAC-SHA256(session_id, secret).
The interactsh adapter expects this token in callback payloads to
confirm a callback originated from this specific session and not a
cross-session collision.
"""
import hashlib
import hmac
import os
import uuid


def derive_canary_hmac(session_id: uuid.UUID, *, secret: bytes | None = None) -> str:
    secret = secret or os.environ.get("OSA_CANARY_SECRET", "osa-canary-v1").encode()
    digest = hmac.new(secret, session_id.bytes, hashlib.sha256).hexdigest()
    return digest[:32]


def verify_canary_hmac(session_id: uuid.UUID, candidate: str, *, secret: bytes | None = None) -> bool:
    expected = derive_canary_hmac(session_id, secret=secret)
    return hmac.compare_digest(expected, candidate)
