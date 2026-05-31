"""Integration tests for PR3.2 IMAGE_REGEX extension — W3 four-namespace allowlist."""
import re

import pytest

from app.infra.socket_proxy_filter import IMAGE_REGEX, validate_create_body


def _body(image: str) -> bytes:
    import json
    return json.dumps({"Image": image}).encode()


def test_osa_kali_still_accepted():
    ok, reason = validate_create_body(_body("osa-kali:latest"))
    assert ok, reason


def test_osa_mitmproxy_accepted():
    ok, reason = validate_create_body(_body("osa-mitmproxy:latest"))
    assert ok, reason


def test_osa_headless_browser_accepted():
    ok, reason = validate_create_body(_body("osa-headless-browser:latest"))
    assert ok, reason


def test_osa_interactsh_accepted():
    ok, reason = validate_create_body(_body("osa-interactsh:latest"))
    assert ok, reason


def test_rogue_image_rejected():
    ok, reason = validate_create_body(_body("nginx:latest"))
    assert not ok
    assert "image_not_allowed" in reason


def test_osa_kali_with_digest_pin_accepted():
    ok, reason = validate_create_body(_body("osa-kali@sha256:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"))
    assert ok, reason


def test_osa_unknown_namespace_rejected():
    ok, reason = validate_create_body(_body("osa-foo:latest"))
    assert not ok
    assert "image_not_allowed" in reason


def test_image_regex_exactly_four_namespaces():
    pattern = IMAGE_REGEX.pattern
    m = re.match(r"^\^\(([^)]+)\)", pattern)
    assert m is not None, f"Expected alternation group at start of IMAGE_REGEX pattern, got: {pattern!r}"
    namespaces = frozenset(m.group(1).split("|"))
    expected = frozenset(["osa-kali", "osa-mitmproxy", "osa-headless-browser", "osa-interactsh"])
    assert namespaces == expected, (
        f"IMAGE_REGEX must list exactly 4 W3 namespaces.\n"
        f"  expected: {expected}\n"
        f"  actual:   {namespaces}"
    )
