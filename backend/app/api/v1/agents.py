"""Agent catalog and template endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User

router = APIRouter(prefix="/agents", tags=["agents"])

# Import agent classes to read their metadata
from app.agents.nmap import NmapAdapter
from app.agents.nuclei import NucleiAdapter
from app.agents.metasploit import MetasploitAdapter
from app.agents.pyrit import PyRITAdapter


def _agent_meta(cls) -> dict:
    return {
        "agent_type": cls.agent_type,
        "docker_image": cls.docker_image,
        "risk_level": cls.risk_level.value if hasattr(cls.risk_level, "value") else str(cls.risk_level),
        "capabilities": cls(None).get_capabilities() if callable(getattr(cls, "get_capabilities", None)) else [],
        "options_schema": getattr(cls, "OPTIONS_SCHEMA", {}),
        "category": "tool",
    }


_TOOL_AGENTS = [NmapAdapter, NucleiAdapter, MetasploitAdapter, PyRITAdapter]

_DOMAIN_AGENTS = [
    {
        "agent_type": "application",
        "category": "domain",
        "risk_level": "medium",
        "description": "Application-layer security testing",
        "capabilities": ["xss", "sqli", "auth_bypass", "business_logic"],
        "options_schema": {
            "type": "object",
            "properties": {
                "intensity": {"type": "string", "enum": ["passive", "active", "aggressive"], "default": "active"},
                "auth_type": {"type": "string", "enum": ["none", "basic", "bearer", "cookie"], "default": "none"},
                "crawl_depth": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
            }
        }
    },
    {
        "agent_type": "web",
        "category": "domain",
        "risk_level": "medium",
        "description": "Web application security assessment",
        "capabilities": ["owasp_top10", "api_testing", "cors_check", "header_analysis"],
        "options_schema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["full", "api_only", "frontend_only"], "default": "full"},
                "tools": {"type": "array", "items": {"type": "string", "enum": ["nuclei", "zap", "nikto", "sqlmap"]}, "default": ["nuclei"]},
            }
        }
    },
    {
        "agent_type": "cloud_azure",
        "category": "domain",
        "risk_level": "high",
        "description": "Azure cloud security assessment",
        "capabilities": ["iam_audit", "storage_audit", "network_audit", "resource_enumeration"],
        "options_schema": {
            "type": "object",
            "properties": {
                "subscription_id": {"type": "string", "description": "Azure subscription ID to assess"},
                "checks": {"type": "array", "items": {"type": "string", "enum": ["iam", "storage", "network", "compute"]}, "default": ["iam", "storage"]},
            }
        }
    },
    {
        "agent_type": "source_code",
        "category": "domain",
        "risk_level": "low",
        "description": "Static source code security analysis",
        "capabilities": ["sast", "secret_detection", "dependency_audit", "code_review"],
        "options_schema": {
            "type": "object",
            "properties": {
                "languages": {"type": "array", "items": {"type": "string"}, "default": ["python", "javascript"]},
                "tools": {"type": "array", "items": {"type": "string", "enum": ["semgrep", "bandit", "trivy", "gitleaks"]}, "default": ["semgrep", "gitleaks"]},
                "include_tests": {"type": "boolean", "default": False},
            }
        }
    },
]

_TEMPLATES = [
    {
        "id": "recon-only",
        "name": "Reconnaissance Only",
        "description": "Passive network and web reconnaissance",
        "steps": [
            {"id": "n1", "agent_type": "nmap", "config": {"scan_profile": "quick"}},
        ],
        "edges": []
    },
    {
        "id": "web-pentest",
        "name": "Web Application Pentest",
        "description": "Comprehensive web application security test",
        "steps": [
            {"id": "n1", "agent_type": "nmap", "config": {"scan_profile": "standard"}},
            {"id": "nu1", "agent_type": "nuclei", "config": {"severity": ["high", "critical"]}},
            {"id": "w1", "agent_type": "web", "config": {"scope": "full"}},
        ],
        "edges": [
            {"source": "n1", "target": "nu1"},
            {"source": "nu1", "target": "w1"},
        ]
    },
    {
        "id": "cloud-azure-baseline",
        "name": "Azure Cloud Baseline",
        "description": "Azure security posture baseline assessment",
        "steps": [
            {"id": "c1", "agent_type": "cloud_azure", "config": {"checks": ["iam", "storage", "network", "compute"]}},
        ],
        "edges": []
    },
    {
        "id": "full-scope",
        "name": "Full Scope Assessment",
        "description": "End-to-end pentest from recon to exploitation",
        "steps": [
            {"id": "n1", "agent_type": "nmap", "config": {"scan_profile": "thorough"}},
            {"id": "nu1", "agent_type": "nuclei", "config": {"severity": ["medium", "high", "critical"]}},
            {"id": "m1", "agent_type": "metasploit", "config": {}},
            {"id": "w1", "agent_type": "web", "config": {"scope": "full"}},
        ],
        "edges": [
            {"source": "n1", "target": "nu1"},
            {"source": "nu1", "target": "m1"},
            {"source": "n1", "target": "w1"},
        ]
    },
]


@router.get("/catalog")
async def get_catalog(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tool_agents = []
    for cls in _TOOL_AGENTS:
        try:
            meta = _agent_meta(cls)
            tool_agents.append(meta)
        except Exception:
            pass
    return {"tool_agents": tool_agents, "domain_agents": _DOMAIN_AGENTS}


@router.get("/catalog/{agent_type}")
async def get_catalog_agent(
    agent_type: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    for cls in _TOOL_AGENTS:
        if cls.agent_type == agent_type:
            return _agent_meta(cls)
    for d in _DOMAIN_AGENTS:
        if d["agent_type"] == agent_type:
            return d
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Agent type '{agent_type}' not found")


@router.get("/templates")
async def get_templates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return {"templates": _TEMPLATES}
