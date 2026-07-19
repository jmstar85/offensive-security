"""Generator grounds its draft plan in the REAL tool registry.

Regression guard for the "invented agent/action" bug: the interview's Generator
used to emit agent/action names like ``recon``/``scanner``/``banner_grab`` that
are NOT registered tools, so the resulting draft plan could not execute. The fix
injects the real tool palette (``registry.palette_text``) into the Generator via
``context["tools_palette"]`` and REQUIRES steps use only listed slugs/actions/tiers.

Covers:
1. ``palette_lines``/``palette_text`` list real slugs + their capabilities and
   exclude ``kali_*`` when kali is disabled (include them when enabled).
2. When ``context["tools_palette"]`` is set, the message the model client
   receives contains the AVAILABLE TOOLS header and real slugs.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.registry import palette_lines, palette_text
from app.orchestrator.roles.generator import Generator


class _CapturingClient:
    """Fake model client that records the ``messages``/``system`` it received."""

    def __init__(self) -> None:
        self.sent_messages: list[dict] = []
        self.sent_system: str | None = None

    async def send(self, *, model_id, messages, system, **_kwargs):
        self.sent_messages = list(messages)
        self.sent_system = system
        envelope = (
            '{"ambiguity": 0.2, "blockers": [], '
            '"reasoning": "grounded", "draft_plan": {"steps": []}}'
        )
        return SimpleNamespace(text=envelope, tokens_in=5, tokens_out=7, raw=None)


def test_palette_lines_lists_real_slugs_and_excludes_kali_when_disabled():
    """Kali OFF: real non-kali slugs present with their capabilities; no kali_*."""
    lines = palette_lines(kali_enabled=False)
    blob = "\n".join(lines)

    # Real slugs are present.
    assert any(line.startswith("- nmap  ") for line in lines)
    assert any(line.startswith("- httpx  ") for line in lines)
    assert any(line.startswith("- passive_recon  ") for line in lines)

    # Each line surfaces the tool's real capabilities (the valid "actions").
    assert "actions: port_scan, service_detection, os_detection" in blob
    assert "actions: secret_scan" in blob  # passive_recon first capability

    # kali_* excluded when the flag is off (mirrors _is_visible_tool).
    assert "kali_" not in blob


def test_palette_lines_includes_kali_when_enabled():
    """Kali ON: kali_* slugs are surfaced too, and the enabled palette is larger."""
    off = palette_lines(kali_enabled=False)
    on = palette_lines(kali_enabled=True)
    on_blob = "\n".join(on)

    assert any(line.startswith("- kali_gobuster  ") for line in on)
    assert "kali_" in on_blob
    assert len(on) > len(off)  # enabling kali strictly adds tools


def test_palette_text_matches_joined_lines():
    """palette_text is just the newline-joined palette_lines."""
    assert palette_text(kali_enabled=False) == "\n".join(palette_lines(kali_enabled=False))


@pytest.mark.asyncio
async def test_generator_prepends_palette_into_user_message():
    """When context['tools_palette'] is set, the client sees the AVAILABLE TOOLS
    header + real slugs prepended to the user content."""
    client = _CapturingClient()
    palette = palette_text(kali_enabled=False)

    role = Generator()
    await role.run(
        performer=None,
        context={
            "user_content": "Recon scanme.nmap.org for open ports",
            "tools_palette": palette,
            "model_client": client,
        },
    )

    assert client.sent_messages, "client must have been called with messages"
    last = client.sent_messages[-1]
    assert last["role"] == "user"
    content = last["content"]

    # Authoritative header + real slugs are grounded in the user message.
    assert "[AVAILABLE TOOLS" in content
    assert "nmap" in content
    assert "httpx" in content
    assert "passive_recon" in content
    # The original user request is preserved after the palette block.
    assert "Recon scanme.nmap.org for open ports" in content


@pytest.mark.asyncio
async def test_generator_without_palette_omits_header():
    """No tools_palette in context → no AVAILABLE TOOLS block (backward compat)."""
    client = _CapturingClient()
    role = Generator()
    await role.run(
        performer=None,
        context={
            "user_content": "hello",
            "model_client": client,
        },
    )
    content = client.sent_messages[-1]["content"]
    assert "[AVAILABLE TOOLS" not in content
    assert content == "hello"
