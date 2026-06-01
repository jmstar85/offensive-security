"""Fernet key rotation primitives — W5/PR5.1.

Production deployments wrap the active Fernet key with a KMS-resident
master key (AWS KMS / GCP KMS / Azure Key Vault). The MultiFernet
primitive transparently decrypts ciphertext encrypted under any active
OR previous key, while always re-encrypting under the FIRST (current)
key. Quarterly rotation appends a new key at index 0; the previous
key migrates to index 1; a key beyond index N is purged.

This module is KMS-agnostic — kms_unwrap is a Protocol; the prod
wiring uses boto3/google-cloud-kms/azure-keyvault, dev uses a local
pass-through.
"""
from __future__ import annotations
import os
from typing import Protocol
from cryptography.fernet import Fernet, MultiFernet

MAX_KEY_RING_SIZE = 3

class KmsUnwrap(Protocol):
    def unwrap(self, wrapped_key: bytes) -> bytes: ...

class LocalPassThroughKms:
    """Dev/test shim — KMS unwrap returns the key verbatim."""
    def unwrap(self, wrapped_key: bytes) -> bytes:
        return wrapped_key

def build_multi_fernet(
    wrapped_keys: list[bytes],
    kms: KmsUnwrap,
) -> MultiFernet:
    """Construct MultiFernet from a list of KMS-wrapped Fernet keys.

    wrapped_keys is ordered current-first; rotation prepends a new
    key. Each entry is unwrapped via kms.unwrap before MultiFernet
    construction. The current key (index 0) is used for new encryptions.
    """
    if not wrapped_keys:
        raise ValueError("at least one Fernet key required")
    if len(wrapped_keys) > MAX_KEY_RING_SIZE:
        raise ValueError(
            f"key ring exceeds MAX_KEY_RING_SIZE={MAX_KEY_RING_SIZE}; purge oldest"
        )
    fernets = [Fernet(kms.unwrap(wk)) for wk in wrapped_keys]
    return MultiFernet(fernets)

def rotate(
    current_wrapped_keys: list[bytes],
    new_wrapped_key: bytes,
) -> list[bytes]:
    """Append a new key at index 0; purge keys beyond MAX_KEY_RING_SIZE."""
    new_ring = [new_wrapped_key] + list(current_wrapped_keys)
    return new_ring[:MAX_KEY_RING_SIZE]

def parse_keyring_env(value: str | None) -> list[bytes]:
    """Read OSA_CREDENTIAL_FERNET_KEYRING env (comma-separated wrapped keys).

    Falls back to a single-key list if only OSA_CREDENTIAL_FERNET_KEY is set.
    """
    if value:
        return [k.strip().encode() for k in value.split(",") if k.strip()]
    legacy = os.environ.get("OSA_CREDENTIAL_FERNET_KEY") or os.environ.get("CREDENTIAL_FERNET_KEY")
    if legacy:
        return [legacy.encode()]
    return []
