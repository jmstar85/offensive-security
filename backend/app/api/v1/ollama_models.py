"""GET /config/ollama/models — live Ollama model list (newflow PR8).

Backend companion to the redesigned `/pentest-sessions/new` provider/model
selector: when the operator picks "Ollama" as the provider, the frontend
calls this endpoint to populate the model dropdown with whatever is actually
pulled on the configured Ollama server, instead of a hardcoded static list.

Proxies `GET {settings.ollama_base_url}/api/tags` (the same server
`OllamaClient` talks to — app/orchestrator/ollama_client.py). Fails soft: if
Ollama is unreachable (connection refused/timeout), returns the configured
default model (`settings.ollama_model`, e.g. "qwen3-14b-96k:latest") with
`reachable: false` so the UI can still offer a usable Ollama option and
surface a "server not reachable" notice, rather than an empty dropdown.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.config import settings
from app.models.user import User

router = APIRouter()


@router.get("/config/ollama/models")
async def get_ollama_models(
    current_user: User = Depends(get_current_user),
) -> dict:
    _ = current_user  # auth required (this leaks internal-network reachability)
    url = f"{settings.ollama_base_url.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.TimeoutException,
    ):
        return {"models": [settings.ollama_model], "reachable": False}
    except httpx.HTTPStatusError:
        # Ollama reachable but returned a 4xx/5xx — treat as unreachable for
        # UI purposes rather than 500ing the page.
        return {"models": [settings.ollama_model], "reachable": False}

    models = [m["name"] for m in (data.get("models") or []) if m.get("name")]
    if not models:
        models = [settings.ollama_model]
    return {"models": models, "reachable": True}
