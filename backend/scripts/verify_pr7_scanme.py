"""PR7 manual verification: real Docker recon against scanme.nmap.org through the
autonomous safety-wired path. Run on the HOST (Docker reachable, images built):

    PYTHONPATH=. .venv/bin/python scripts/verify_pr7_scanme.py

Layer 1 isolates the real nmap container; Layer 2 drives the autonomous
Performer._dispatch_tool (per-dispatch tier gate + shared runtime safety helper).
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

TARGET = {"ip_ranges": ["45.33.32.156/32"], "domains": ["scanme.nmap.org"]}
WHITELIST = {"ip_ranges": ["45.33.32.156/32"], "domains": ["scanme.nmap.org"]}
# Targeted fast scan of known-open scanme ports for a quick, deterministic check.
NMAP_CFG = {"network": "bridge", "flags": "-p 22,80,9929 -sV --open -T4 -Pn"}


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()

    async def _flush() -> None:
        pass

    db.flush = _flush
    db.execute = AsyncMock()
    return db


async def layer1_raw_adapter() -> list[dict] | None:
    from app.agents.registry import get_adapter

    adapter = get_adapter("nmap")
    findings = None
    async for ev in adapter.execute(TARGET, NMAP_CFG, []):
        if ev.event_type == "log":
            print("   [nmap]", ev.data.get("line", "").rstrip())
        if ev.event_type == "status" and "result" in ev.data:
            findings = ev.data["result"].get("findings")
    print("   LAYER1 findings:", findings)
    return findings


async def layer2_autonomous_dispatch() -> dict:
    from app.orchestrator.performer import Performer

    p = Performer(_mock_db(), uuid.uuid4())
    p.bind_live_execution(
        target=TARGET,
        approval_flags={"approved_active_recon": True},  # nmap = active_recon tier
        whitelist_rules=WHITELIST,
        actor_id="verify-pr7",
    )
    res = await p._dispatch_tool("nmap", {"config": NMAP_CFG})
    print("   LAYER2 result:", {
        k: res.get(k) for k in
        ("approved", "blocked_reason", "executed", "killed", "safety_violation")
    })
    print("   LAYER2 findings:", res.get("findings"))
    return res


async def main() -> None:
    print("=== LAYER 1: raw nmap adapter container vs scanme.nmap.org ===")
    f1 = await layer1_raw_adapter()
    print("\n=== LAYER 2: autonomous _dispatch_tool (tier gate + runtime helper) vs scanme ===")
    r2 = await layer2_autonomous_dispatch()

    ok = bool(f1) and r2.get("executed") is True and bool(r2.get("findings"))
    print("\nVERIFY_RESULT:", "PASS" if ok else "FAIL")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
