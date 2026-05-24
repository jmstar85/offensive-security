"""Allowlist-only HTTPX transport.

Blocks any outbound HTTP request whose hostname is not present (or whose
wildcard parent is not present) in ``OSA_PASSIVE_EGRESS_ALLOWLIST`` (comma-
separated env var). Used by every entrypoint in the osa-passive-recon image.
"""
from __future__ import annotations

import fnmatch
import os
from typing import Iterable

import httpx


class _EgressDenied(httpx.RequestError):
    """Raised when a target is not on the allowlist."""


def _parse_allowlist(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def _hostname_allowed(host: str, patterns: Iterable[str]) -> bool:
    host = host.lower()
    for pattern in patterns:
        if fnmatch.fnmatch(host, pattern):
            return True
    return False


class AllowlistTransport(httpx.BaseTransport):
    """Synchronous transport wrapper enforcing the egress allowlist."""

    def __init__(self, inner: httpx.BaseTransport | None = None) -> None:
        self._inner = inner or httpx.HTTPTransport()
        self._patterns = _parse_allowlist(os.getenv("OSA_PASSIVE_EGRESS_ALLOWLIST"))

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        if not _hostname_allowed(host, self._patterns):
            raise _EgressDenied(
                f"egress denied: {host} is not in OSA_PASSIVE_EGRESS_ALLOWLIST",
                request=request,
            )
        return self._inner.handle_request(request)


def make_client(timeout_seconds: float = 10.0) -> httpx.Client:
    return httpx.Client(
        transport=AllowlistTransport(),
        timeout=timeout_seconds,
        follow_redirects=False,
    )
