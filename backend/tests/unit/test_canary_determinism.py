from __future__ import annotations

import json
import uuid

from app.safety.conversation_scrubber import ConversationScrubber


def _strip_canary(d: dict) -> dict:
    """Return copy of d with canary key removed from understanding.raw_signals."""
    import copy
    result = copy.deepcopy(d)
    raw = result.get("understanding", {}).get("raw_signals", {})
    raw.pop("canary", None)
    return result


class TestCanaryDeterminism:
    def test_canary_strip_yields_byte_identical_coordinator_output(self):
        session_id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        s = ConversationScrubber(session_id)
        canary_hex = s._canary

        output_with_canary = {
            "understanding": {
                "target_kind": "web_app",
                "raw_signals": {"canary": canary_hex, "prompt": "p"},
            },
            "plan_of_work": {"steps": ["recon", "scan"], "priority": "high"},
        }
        output_without_canary = {
            "understanding": {
                "target_kind": "web_app",
                "raw_signals": {"prompt": "p"},
            },
            "plan_of_work": {"steps": ["recon", "scan"], "priority": "high"},
        }

        stripped = _strip_canary(output_with_canary)
        assert json.dumps(stripped, sort_keys=True) == json.dumps(output_without_canary, sort_keys=True)

    def test_canary_value_deterministic_across_runs(self):
        session_id = uuid.UUID("12345678-abcd-ef01-2345-6789abcdef01")
        canaries = []
        for _ in range(5):
            s = ConversationScrubber(session_id)
            canaries.append(s._canary)
        assert len(set(canaries)) == 1

    def test_canary_value_independent_of_text_content(self):
        session_id = uuid.uuid4()
        s = ConversationScrubber(session_id)
        canary_before = s._canary
        # Scrub various texts
        s.scrub("hello world normal text")
        s.scrub("sk-someapikey1234567890")
        s.scrub("another text with different content 12345")
        canary_after = s._canary
        assert canary_before == canary_after
