"""Agent catalog and workflow template endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.domains import list_domain_agents
from app.agents.registry import get_tool_entry, list_tool_entries
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

router = APIRouter()


def _tool_meta(entry) -> dict:
    return {
        "agent_type": entry.slug,
        "docker_image": entry.docker_image,
        "risk_level": entry.default_risk_band.value,
        "capabilities": list(entry.capabilities),
        "options_schema": getattr(entry.adapter_cls, "OPTIONS_SCHEMA", {}),
        "category": "tool",
        "tier": entry.tier,
        "executable": True,
        "is_destructive_capable": entry.is_destructive_capable,
    }


def _domain_meta(agent) -> dict:
    return {
        "agent_type": agent.slug,
        "display_name": agent.display_name,
        "category": "domain",
        "risk_level": "medium" if agent.default_risk_tier == "active_recon" else "low",
        "description": agent.persona_prompt,
        "capabilities": list(agent.intent_slugs),
        "options_schema": {},
        "tier": agent.default_risk_tier,
        "executable": False,
        "admin_only": agent.admin_only,
    }


_TEMPLATES = [
    {
        "id": "recon-only",
        "name": "Reconnaissance Only",
        "description": "Passive network and web reconnaissance",
        "executable": True,
        "steps": [
            {"id": "n1", "agent": "nmap", "action": "port_scan", "config": {"scan_profile": "quick"}},
        ],
        "edges": [],
    },
    {
        "id": "web-pentest",
        "name": "Web Application Pentest",
        "description": "Executable web recon workflow using supported tool agents",
        "executable": True,
        "steps": [
            {"id": "n1", "agent": "nmap", "action": "port_scan", "config": {"scan_profile": "standard"}},
            {
                "id": "nu1",
                "agent": "nuclei",
                "action": "vulnerability_scan",
                "config": {"severity": ["high", "critical"]},
            },
        ],
        "edges": [
            {"source": "n1", "target": "nu1"},
        ],
    },
    {
        "id": "full-scope",
        "name": "Full Scope Assessment",
        "description": "Executable tool-agent assessment workflow",
        "executable": True,
        "steps": [
            {"id": "n1", "agent": "nmap", "action": "port_scan", "config": {"scan_profile": "thorough"}},
            {
                "id": "nu1",
                "agent": "nuclei",
                "action": "vulnerability_scan",
                "config": {"severity": ["medium", "high", "critical"]},
            },
            {
                "id": "m1",
                "agent": "metasploit",
                "action": "approved_module_run",
                "config": {"module": "auxiliary/scanner/portscan/tcp"},
            },
        ],
        "edges": [
            {"source": "n1", "target": "nu1"},
            {"source": "nu1", "target": "m1"},
        ],
    },
]


def _is_visible_tool(entry) -> bool:
    """Hide kali_* tools from the catalog when OSA_KALI_BACKEND_ENABLED is off.

    The orchestrator already raises KaliBackendDisabledError at execution
    time, but surfacing kali_* in the catalog when the flag is off would
    invite users to build workflows that fail later. palette_for_domain
    applies the same filter at the planner side; this keeps the two
    catalog surfaces consistent.
    """
    if entry.slug.startswith("kali_") and not settings.osa_kali_backend_enabled:
        return False
    return True


@router.get("/catalog")
async def get_catalog(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return {
        "tool_agents": [
            _tool_meta(entry)
            for entry in list_tool_entries()
            if _is_visible_tool(entry)
        ],
        "domain_agents": [_domain_meta(agent) for agent in list_domain_agents()],
    }


@router.get("/catalog/{agent_type}")
async def get_catalog_agent(
    agent_type: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tool = get_tool_entry(agent_type)
    if tool and _is_visible_tool(tool):
        return _tool_meta(tool)
    for agent in list_domain_agents():
        if agent.slug == agent_type:
            return _domain_meta(agent)
    raise HTTPException(status_code=404, detail=f"Agent type '{agent_type}' not found")


@router.get("/templates")
async def get_templates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return {"templates": _TEMPLATES}
