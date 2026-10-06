"""Structure-preserving conversation masking (Phase 1-a), in the safety layer so
both the API routers and the orchestrator persistence sites can reuse ONE
implementation (no orchestrator->api import). Wraps ConversationScrubber."""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.safety.conversation_scrubber import ConversationScrubber


def scrub_text(scrubber: ConversationScrubber, s: str) -> str:
    """Scrub one string. If it is a serialized JSON object/array, parse it, scrub
    its string leaves, and re-serialize so structure + numeric fields survive (a
    raw regex over serialized JSON can eat punctuation and corrupt it). Plain
    (non-JSON) strings are scrubbed directly."""
    try:
        parsed = json.loads(s)
    except (ValueError, TypeError):
        return scrubber.scrub(s).scrubbed_text
    if isinstance(parsed, (dict, list)):
        return json.dumps(scrub_payload(scrubber, parsed))
    return scrubber.scrub(s).scrubbed_text


def scrub_payload(scrubber: ConversationScrubber, value: Any) -> Any:
    """Recursively scrub string leaves; preserve numbers/bools/None and structure.
    String leaves route through scrub_text so an embedded JSON envelope stays valid
    JSON and numeric metadata (ambiguity, token usage) is untouched."""
    if isinstance(value, str):
        return scrub_text(scrubber, value)
    if isinstance(value, dict):
        return {k: scrub_payload(scrubber, v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_payload(scrubber, v) for v in value]
    return value


def scrub_json_str(session_id: uuid.UUID, s: str) -> str:
    """Scrub a standalone JSON/text string at a storage or live-response boundary."""
    return scrub_text(ConversationScrubber(session_id=session_id), s)


def scrub_messages(session_id: uuid.UUID, messages: Any) -> Any:
    """Scrub a list of role-message dicts (e.g. MsgChain.messages_json) for storage."""
    return scrub_payload(ConversationScrubber(session_id=session_id), messages)
