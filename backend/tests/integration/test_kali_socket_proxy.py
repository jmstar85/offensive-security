"""PR-7 — socket-proxy + image-regex middleware integration test.

Covers the seven assertions enumerated in the consensus plan (A2.1.(e)):
    (e.1) POST /images/create                   → 403
    (e.2) GET  /networks                        → 403
    (e.3) POST /containers/{id}/exec            → 403
    (e.4) POST /volumes/create                  → 403
    (e.5) GET  /info                            → 403
    (e.6) POST /containers/create  Image=alpine → 403 (middleware rejects body)
    (e.7) POST /containers/create  Image=osa-kali:<digest> → 201

The middleware FastAPI app talks to a ``httpx.MockTransport`` that mimics
the tecnativa proxy's endpoint allowlist (only ``/containers/create`` is
reachable; everything else returns 403). This isolates the middleware logic
from the network and keeps the test runnable without docker.
"""
from __future__ import annotations

import httpx
import pytest

from app.infra.socket_proxy_filter import (
    IMAGE_REGEX,
    create_app,
    validate_create_body,
)


# --- Pure validator ----------------------------------------------------------

def test_image_regex_accepts_osa_kali_variants():
    for img in ("osa-kali", "osa-kali:latest", "osa-kali:abc123",
                "osa-kali@sha256:" + "0" * 64):
        assert IMAGE_REGEX.match(img), img


def test_image_regex_rejects_other_images():
    for img in ("alpine", "osa-agent-nmap:latest", "osa-kalix",
                "myrepo/osa-kali", "ubuntu:22.04"):
        assert IMAGE_REGEX.match(img) is None, img


def test_validate_create_body_happy_path():
    ok, reason = validate_create_body(b'{"Image": "osa-kali:abc"}')
    assert ok and reason == ""


@pytest.mark.parametrize("body,expected_reason", [
    (b"", "empty_body"),
    (b"not-json", "invalid_json"),
    (b'"a string"', "non_object_payload"),
    (b'{}', "missing_image"),
    (b'{"Image": "alpine"}', "image_not_allowed:'alpine'"),
    (b'{"Image": 1}', "missing_image"),
])
def test_validate_create_body_rejects(body, expected_reason):
    ok, reason = validate_create_body(body)
    assert ok is False
    assert reason == expected_reason


# --- Integration: FastAPI ASGI client + httpx.MockTransport upstream --------

def _mock_upstream_handler(request: httpx.Request) -> httpx.Response:
    """tecnativa proxy stand-in: 403 everywhere except /containers/create."""
    path = request.url.path
    method = request.method
    if method == "POST" and path == "/containers/create":
        return httpx.Response(201, json={"Id": "ctr-abc"})
    if method == "POST" and path.endswith("/start"):
        return httpx.Response(204)
    return httpx.Response(403, json={"message": f"upstream proxy 403: {method} {path}"})


@pytest.fixture
async def client():
    app = create_app(
        "http://mock-upstream",
        transport=httpx.MockTransport(_mock_upstream_handler),
    )
    asgi = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=asgi, base_url="http://kali-socket-proxy-filter",
    ) as c:
        yield c


# --- The seven assertions ----------------------------------------------------

async def test_e1_images_create_returns_403(client):
    r = await client.post("/images/create", json={"fromImage": "alpine"})
    assert r.status_code == 403


async def test_e2_networks_returns_403(client):
    r = await client.get("/networks")
    assert r.status_code == 403


async def test_e3_container_exec_returns_403(client):
    r = await client.post("/containers/abc/exec", json={"Cmd": ["sh"]})
    assert r.status_code == 403


async def test_e4_volumes_create_returns_403(client):
    r = await client.post("/volumes/create", json={"Name": "v"})
    assert r.status_code == 403


async def test_e5_info_returns_403(client):
    r = await client.get("/info")
    assert r.status_code == 403


async def test_e6_containers_create_alpine_returns_403(client):
    r = await client.post("/containers/create", json={"Image": "alpine"})
    assert r.status_code == 403
    body = r.json()
    assert "alpine" in body["message"]


async def test_e7_containers_create_osa_kali_returns_201(client):
    r = await client.post(
        "/containers/create",
        json={
            "Image": "osa-kali@sha256:" + "0" * 64,
            "Cmd": ["/usr/bin/gobuster", "dir", "-u", "http://t/",
                    "-w", "/wordlists/c.txt"],
        },
    )
    assert r.status_code == 201
    assert r.json() == {"Id": "ctr-abc"}
