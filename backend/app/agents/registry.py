"""Agent registry — maps agent_type names to adapter classes."""
from __future__ import annotations

from app.agents.backends.docker import get_docker_backend
from app.agents.base import AgentAdapter
from app.agents.metasploit import MetasploitAdapter
from app.agents.nmap import NmapAdapter
from app.agents.nuclei import NucleiAdapter
from app.agents.pyrit import PyRITAdapter

_ADAPTERS: dict[str, type[AgentAdapter]] = {
    "nmap": NmapAdapter,
    "nuclei": NucleiAdapter,
    "metasploit": MetasploitAdapter,
    "pyrit": PyRITAdapter,
}


def get_adapter(agent_type: str) -> AgentAdapter:
    cls = _ADAPTERS.get(agent_type)
    if not cls:
        raise ValueError(f"Unknown agent type: {agent_type}")
    return cls(backend=get_docker_backend())


def list_agent_types() -> list[str]:
    return list(_ADAPTERS.keys())
