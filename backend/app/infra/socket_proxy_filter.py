"""docker-socket-proxy front-line image filter (PR-7).

`tecnativa/docker-socket-proxy` enforces endpoint allowlisting, but it does
not inspect request bodies. The Kali-coexistence threat model (Pre-mortem
F3) requires that a backend prompt-injection cannot pivot the *KaliBackend*
docker client into launching arbitrary images — the proxy alone allows any
``POST /containers/create`` payload through.

This module is the body-inspecting middleware that sits between the backend
and the tecnativa proxy. It accepts every other request unchanged and
rejects ``POST /containers/create`` whose JSON body's ``Image`` field does
not match ``IMAGE_REGEX``.

The validator (``validate_create_body``) is pure and the FastAPI app factory
(``create_app``) is a thin wrapper that forwards via ``httpx.AsyncClient``.
The validator is the unit-tested surface; the FastAPI app is integration-
tested against an ASGI httpx client with a mocked upstream.
"""
import json
import os
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

IMAGE_REGEX = re.compile(r"^osa-kali(?:[:@].+)?$")
"""Only osa-kali images may be created through this middleware."""

CREATE_PATH = "/containers/create"


def validate_create_body(body: bytes) -> tuple[bool, str]:
    """Return (ok, reason) for a POST /containers/create body.

    Reject when:
      - body is not valid JSON
      - the ``Image`` field is missing or non-string
      - ``Image`` does not match ``IMAGE_REGEX``
    """
    if not body:
        return False, "empty_body"
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return False, "invalid_json"
    if not isinstance(payload, dict):
        return False, "non_object_payload"
    image = payload.get("Image")
    if not isinstance(image, str) or not image:
        return False, "missing_image"
    if IMAGE_REGEX.match(image) is None:
        return False, f"image_not_allowed:{image!r}"
    return True, ""


def create_app(upstream_url: str, transport: Optional[httpx.AsyncBaseTransport] = None) -> FastAPI:
    """Build a FastAPI catch-all reverse proxy in front of docker-socket-proxy.

    ``upstream_url`` is the tecnativa proxy base URL, e.g.
    ``http://docker-socket-proxy:2375``. ``transport`` is injectable so the
    integration test can swap in an ``httpx.MockTransport``. Every request is
    forwarded unchanged except POST /containers/create, which must pass
    ``validate_create_body``.
    """
    client = httpx.AsyncClient(
        base_url=upstream_url, timeout=30.0, transport=transport,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await client.aclose()

    app = FastAPI(title="kali-socket-proxy-filter", lifespan=lifespan)

    @app.api_route(
        "/{full_path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    )
    async def forward(full_path: str, request: Request) -> Response:
        body = await request.body()
        if request.method == "POST" and request.url.path.endswith(CREATE_PATH):
            ok, reason = validate_create_body(body)
            if not ok:
                return JSONResponse(
                    {"message": f"socket-proxy-filter: {reason}"},
                    status_code=403,
                )

        upstream_response = await client.request(
            method=request.method,
            url=f"/{full_path}",
            content=body,
            params=request.query_params,
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
        )
        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            headers={k: v for k, v in upstream_response.headers.items()
                     if k.lower() not in {"content-length", "transfer-encoding"}},
            media_type=upstream_response.headers.get("content-type"),
        )

    return app


# Allowed proxy endpoints (allowlist enforced by tecnativa/docker-socket-proxy
# via env vars; mirrored here for documentation and reference by tests).
PROXY_ALLOWED_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("POST", "/containers/create"),
    ("POST", "/containers/{id}/start"),
    ("POST", "/containers/{id}/stop"),
    ("GET",  "/containers/{id}/json"),
    ("GET",  "/containers/{id}/logs"),
    ("DELETE", "/containers/{id}"),
)


def env_app_factory() -> FastAPI:
    """uvicorn --factory entry-point.

    Reads the upstream proxy URL from SOCKET_PROXY_UPSTREAM (compose injects
    it pointing at tecnativa/docker-socket-proxy). create_app keeps the
    upstream argument explicit for unit-testability; this thin wrapper makes
    it usable with `uvicorn --factory` which requires a zero-arg callable.
    """
    upstream = os.environ.get(
        "SOCKET_PROXY_UPSTREAM", "http://docker-socket-proxy:2375"
    )
    return create_app(upstream)
