"""Single-sourced pure tool-call envelope parser/validator (PR7 / Improvement 1).

Both the Pentester's live tool-use loop (``roles/pentester.py``) and the
role-free ``AssistantService.turn`` (``assistant_service.py``) call this ONE pure
function to interpret a model's JSON tool-call envelope. Extracting it here means
the more-adversarial operator-chat path does NOT hand-write a second parser, so
any future injection-hardening of the extractor is inherited by both loops for
free (AC#12b).

The function is a PURE, side-effect-free interpretation of the raw model text —
no audit, no dispatch, no I/O. Callers keep their own control flow (byte-identical
for Pentester): they read the fields of the returned :class:`ToolEnvelope` and
branch exactly as they did against the inline expressions this replaces.

Semantics are preserved verbatim from the original Pentester inline parse
(pentester.py, pre-PR7):

    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, TypeError):   -> parse_error="envelope_parse_failure"
    if not isinstance(envelope, dict):          -> parse_error="envelope_not_object"
    slug = envelope.get("tool") or envelope.get("name")
    done = envelope.get("done") is True or slug == "done"
    ask  = slug == "ask" or not slug
    inp  = envelope.get("input") if dict else envelope
    payload = {intent, config, description}

NOTE (deviation from the plan's literal ``parse_tool_envelope -> ToolCall | None``
signature): a bare ``ToolCall | None`` cannot distinguish
``envelope_parse_failure`` from ``envelope_not_object``, and the Pentester
byte-identical tests assert those two distinct ``error`` strings. We therefore
return a richer :class:`ToolEnvelope` result object that carries ``parse_error``
plus the extracted fields — the single source of truth for envelope semantics.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolEnvelope:
    """Pure interpretation of a model's tool-call envelope.

    ``parse_error`` is set (and every other field left at its default) when the
    raw text is not valid JSON (``"envelope_parse_failure"``) or is valid JSON
    but not an object (``"envelope_not_object"``). Otherwise ``parse_error`` is
    ``None`` and the extracted fields describe the tool call.
    """

    parse_error: str | None = None
    envelope: dict[str, Any] | None = None
    slug: str | None = None
    is_done: bool = False
    summary: str = ""
    is_ask: bool = False
    ask_text: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


def parse_tool_envelope(text: str) -> ToolEnvelope:
    """Parse+validate a raw model response into a :class:`ToolEnvelope` (PURE).

    Mirrors the Pentester's original inline parse exactly so the swap is
    byte-identical, and gives the Assistant loop identical rejection of
    malformed / injection envelopes (AC#12b).
    """
    try:
        envelope = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return ToolEnvelope(parse_error="envelope_parse_failure")

    if not isinstance(envelope, dict):
        return ToolEnvelope(parse_error="envelope_not_object")

    slug = envelope.get("tool") or envelope.get("name")
    is_done = envelope.get("done") is True or slug == "done"
    summary = envelope.get("summary", "")
    is_ask = slug == "ask" or not slug
    ask_text = envelope.get("intent") or envelope.get("summary", "")

    raw_inp = envelope.get("input")
    inp = raw_inp if isinstance(raw_inp, dict) else envelope
    payload = {
        "intent": inp.get("intent"),
        "config": inp.get("config", {}),
        "description": inp.get("description", ""),
    }

    return ToolEnvelope(
        parse_error=None,
        envelope=envelope,
        slug=slug,
        is_done=is_done,
        summary=summary,
        is_ask=is_ask,
        ask_text=ask_text,
        payload=payload,
    )
