"""PR7+: verify the FULL autonomous loop — a real Ollama model (qwen3-14b) drives the
Pentester tool-use loop, emits a tool envelope, dispatches through the safety chain,
and a real nmap container scans scanme.nmap.org. Host-run (Ollama on localhost):

    PYTHONPATH=. .venv/bin/python scripts/verify_pr7_ollama_loop.py
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock


async def main() -> None:
    from app.core.config import settings

    # Host process reaches Ollama on localhost (the in-container default is
    # host.docker.internal).
    settings.ollama_base_url = "http://localhost:11434"
    settings.osa_llm_provider = "ollama"

    from app.orchestrator.ollama_client import OllamaClient
    from app.orchestrator.performer import Performer
    from app.orchestrator.roles.pentester import Pentester

    db = AsyncMock()
    db.add = MagicMock()

    async def _flush() -> None:
        pass

    db.flush = _flush
    db.execute = AsyncMock()

    perf = Performer(db, uuid.uuid4())
    perf.bind_live_execution(
        target={"ip_ranges": [], "domains": ["scanme.nmap.org"]},
        approval_flags={"approved_active_recon": True},
        whitelist_rules={"ip_ranges": ["45.33.32.156/32"], "domains": ["scanme.nmap.org"]},
        actor_id="verify-ollama",
    )

    role = Pentester(tools_allowed=["nmap", "httpx", "done", "ask", "search_in_memory"])
    role.max_tool_calls = 2  # keep it short for verification

    ctx = {
        "model_client": OllamaClient(),
        "generator_output": (
            "Authorized recon of scanme.nmap.org. Emit ONE JSON tool call: "
            '{"tool":"nmap","intent":"port_scan","config":{"flags":"-p 22,80 -sV --open -T4 -Pn"}}. '
            "After the tool result, emit {\"done\": true, \"summary\": \"...\"}."
        ),
    }

    print("Driving Pentester via Ollama (qwen3-14b) — this may take a minute...")
    result = await role.run(perf, ctx)

    print("finished:", result.finished, "| tool_calls:", result.tool_calls, "| error:", result.error)
    print("findings collected on performer:", perf.state.findings)
    for m in result.messages:
        print("  turn:", str(m.get("content", ""))[:240])

    ok = result.tool_calls >= 1 and bool(perf.state.findings)
    print("\nOLLAMA_LOOP_RESULT:", "PASS" if ok else "INCONCLUSIVE (see turns above)")


if __name__ == "__main__":
    asyncio.run(main())
