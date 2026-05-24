"""GET /api/v1/domain-agents — list domain-agent personas with derived palettes.

Plan v3.2.1 §3 — exposes the in-code DOMAIN_AGENTS dict over HTTP so the
frontend Workflow page can render persona pickers and tool palettes.
Admin-only domain agents (e.g., mobile-agent) are filtered out for non-admin
callers.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.agents.domains import DOMAIN_AGENTS, get_domain_agent
from app.agents.registry import palette_for_domain
from app.api.deps import get_current_user
from app.models.user import User, UserRole

router = APIRouter()


class ToolPaletteItem(BaseModel):
    slug: str
    tier: str
    capabilities: list[str]
    docker_image: str
    default_risk_band: str
    is_destructive_capable: bool


class DomainAgentResponse(BaseModel):
    slug: str
    display_name: str
    knowledge_pack_slug: str
    tool_tags: list[str]
    default_risk_tier: str
    admin_only: bool
    persona_prompt: str
    intent_slugs: list[str]
    tool_palette: list[ToolPaletteItem]


def _serialize(agent_slug: str) -> DomainAgentResponse:
    agent = DOMAIN_AGENTS[agent_slug]
    palette = palette_for_domain(agent.tool_tags)
    return DomainAgentResponse(
        slug=agent.slug,
        display_name=agent.display_name,
        knowledge_pack_slug=agent.knowledge_pack_slug,
        tool_tags=sorted(agent.tool_tags),
        default_risk_tier=agent.default_risk_tier,
        admin_only=agent.admin_only,
        persona_prompt=agent.persona_prompt,
        intent_slugs=list(agent.intent_slugs),
        tool_palette=[
            ToolPaletteItem(
                slug=e.slug,
                tier=e.tier,
                capabilities=list(e.capabilities),
                docker_image=e.docker_image,
                default_risk_band=e.default_risk_band.value,
                is_destructive_capable=e.is_destructive_capable,
            )
            for e in palette
        ],
    )


@router.get("/", response_model=list[DomainAgentResponse])
async def list_agents(current_user: User = Depends(get_current_user)):
    """Return all visible domain agents.

    Admin-only agents are filtered out for non-admin users.
    """
    is_admin = current_user.role == UserRole.ADMIN
    return [
        _serialize(slug)
        for slug, agent in DOMAIN_AGENTS.items()
        if is_admin or not agent.admin_only
    ]


@router.get("/{slug}", response_model=DomainAgentResponse)
async def get_agent(slug: str, current_user: User = Depends(get_current_user)):
    agent = get_domain_agent(slug)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Unknown domain agent: {slug}")
    if agent.admin_only and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail=f"Domain agent {slug} requires admin role",
        )
    return _serialize(slug)
