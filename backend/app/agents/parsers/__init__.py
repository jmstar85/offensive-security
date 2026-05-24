"""Mandatory per-tool parser plugins for the Kali coexistence path.

Plan v1 mandates a registered parser for every Kali tool — KaliExecAdapter
refuses to fall back to a generic line-mode parser. Register new tool
parsers here as ``register_parser(slug, parse_func)``.
"""
from __future__ import annotations

from typing import Callable

from app.agents.base import AgentResult

ParseFn = Callable[[str, str], AgentResult]  # (raw_output, agent_type) -> AgentResult

_PARSERS: dict[str, ParseFn] = {}


def register_parser(slug: str, parser: ParseFn) -> None:
    if slug in _PARSERS:
        raise ValueError(f"parser already registered for {slug}")
    _PARSERS[slug] = parser


def get_parser(slug: str) -> ParseFn:
    if slug not in _PARSERS:
        raise NotImplementedError(
            f"no parser registered for Kali tool slug {slug!r}; "
            f"every kali_* adapter must ship a parser plugin (no generic fallback)"
        )
    return _PARSERS[slug]


def has_parser(slug: str) -> bool:
    return slug in _PARSERS


# Eagerly register the v1 parsers so importers of KaliExecAdapter see them.
from app.agents.parsers import gobuster as _gobuster  # noqa: E402
from app.agents.parsers import nikto as _nikto  # noqa: E402
from app.agents.parsers import sqlmap as _sqlmap  # noqa: E402

register_parser("gobuster", _gobuster.parse)
register_parser("sqlmap", _sqlmap.parse)
register_parser("nikto", _nikto.parse)
