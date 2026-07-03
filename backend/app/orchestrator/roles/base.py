"""Role abstract base class for the v4.0 Performer engine (PentAGI port).

A Role is differentiated by its system prompt, LLM model binding, tool palette,
and iteration caps — NOT by class hierarchy. Concrete roles (Generator,
Pentester, Memorist, Adviser, Reflector, Reporter) subclass `Role` and override
`run()`; the Performer engine instantiates and runs them generically.

Caps inherited from PentAGI's `performer.go`:
- `max_tool_calls=100` (Pentester / general)
- `max_tool_calls=20` (Memorist / Generator / Reporter / limited)
- `retries=3` (Reflector wrap, in Performer)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RoleResult:
    """Return value of `Role.run()`. Performer persists this to MsgChain."""

    role_name: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    finished: bool = False  # True if role emitted `done` tool, False if still in chain
    tool_calls: int = 0
    usage_input_tokens: int = 0
    usage_output_tokens: int = 0
    error: str | None = None


@dataclass
class Role(ABC):
    """Abstract role contract. Instances are created by the Performer per session."""

    name: str
    system_prompt: str
    llm_model: str  # e.g. "claude-sonnet-4-6"
    tools_allowed: list[str] = field(default_factory=list)
    max_tool_calls: int = 20

    @abstractmethod
    async def run(
        self,
        performer: "Performer",  # type: ignore[name-defined]
        context: dict[str, Any],
        client_factory: Any = None,
    ) -> RoleResult:
        """Execute one chain of this role within a Performer session.

        Concrete implementations ship in P2a. The abstract method ensures the
        Role contract is uniform across the 6 roles.

        ``client_factory`` (PR6, Improvement 3) is the per-invocation, user-id
        bound ``client_factory(role_name)`` callable injected uniformly at the
        two role-launch chokepoints (``run_session``'s ``reflector_wrap`` and
        ``delegate_tool_call``). Consuming roles resolve their LLM client via
        it; non-consuming roles accept-and-ignore it. It carries ``=None`` so a
        future role subclassing this base fails closed at build time if it
        forgets the kwarg (round-6 signature contract).
        """
        raise NotImplementedError("Concrete roles override run() in P2a")
