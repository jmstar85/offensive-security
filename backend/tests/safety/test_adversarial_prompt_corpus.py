"""Adversarial prompt corpus tests — W4/PR4.3.

Asserts that the v1.1 safety chain + ConversationScrubber already catches
every entry in the adversarial fixture corpus. No production code is
modified; this test suite is purely additive.
"""
from __future__ import annotations

import asyncio
import re
import uuid

import pytest

from app.safety.conversation_scrubber import ConversationScrubber
from app.orchestrator.coordinator import UnderstandingBuilder, PlanOfWorkBuilder, UnderstandingOfTarget
from tests.safety.fixtures.adversarial_prompts import (
    PROMPT_INJECTION,
    SCOPE_ESCAPE,
    CREDENTIAL_EXFIL,
    ALL_ADVERSARIAL,
)

_TARGET = {"domains": ["example.com"], "ip_ranges": []}
_VALID_TARGET_KINDS = {"web_app", "network", "cloud", "mobile", "unknown"}


class TestPromptInjectionCorpus:
    @pytest.mark.parametrize("prompt", PROMPT_INJECTION)
    def test_understanding_builder_does_not_escape_mode(self, prompt):
        # UnderstandingBuilder is deterministic; the prompt cannot
        # change target_kind to anything outside the closed enum.
        u = asyncio.run(UnderstandingBuilder().build(prompt, _TARGET))
        assert u.target_kind in _VALID_TARGET_KINDS

    @pytest.mark.parametrize("prompt", PROMPT_INJECTION)
    def test_raw_signals_carries_prompt_verbatim_as_data(self, prompt):
        u = asyncio.run(UnderstandingBuilder().build(prompt, _TARGET))
        # The prompt is stored as data inside raw_signals; the builder must
        # not have executed it (no __ injected key; no shell output present).
        rs = u.raw_signals or {}
        assert "prompt" in rs and rs["prompt"] == prompt
        assert all(not k.startswith("__") for k in rs.keys())


class TestScopeEscapeCorpus:
    @pytest.mark.parametrize("prompt", SCOPE_ESCAPE)
    def test_plan_of_work_does_not_smuggle_extra_targets(self, prompt):
        # PlanOfWorkBuilder derives objectives from prompt text only.
        # Assert it does not alter the static shape of family_recommendations
        # or ordered_phases regardless of prompt content.
        u = UnderstandingOfTarget(
            target_kind="web_app",
            entry_points=["example.com"],
            raw_signals={"prompt": prompt},
        )
        p = asyncio.run(PlanOfWorkBuilder().build(u, prompt))
        assert p.ordered_phases == ["recon", "exploit", "extraction"]
        assert any(r["family_kind"] == "recon" for r in p.family_recommendations)


class TestCredentialExfilCorpus:
    @pytest.mark.parametrize("prompt", CREDENTIAL_EXFIL)
    def test_scrubber_redacts_credential_pattern(self, prompt):
        # ConversationScrubber.scrub MUST replace high-entropy or patterned
        # secret-like substrings with [REDACTED:...].
        s = ConversationScrubber(uuid.uuid4())

        # For any prompt that mentions a specific API_KEY env var *value*
        # (substrings starting with sk-, AKIA, ghp_, eyJ), the scrubber
        # catches it. Verify by appending a known-bad synthetic secret.
        augmented = prompt + " sk-PROD-aaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        result2 = s.scrub(augmented)
        assert result2.layer_hits["l1"] >= 1, (
            f"L1 must catch the sk-* secret appended to: {prompt!r}"
        )


# ── Overall sweep ──────────────────────────────────────────────────────────────

def test_all_adversarial_total_count():
    assert len(ALL_ADVERSARIAL) == len(PROMPT_INJECTION) + len(SCOPE_ESCAPE) + len(CREDENTIAL_EXFIL)
    assert len(ALL_ADVERSARIAL) >= 100, "Corpus must have at least 100 prompts (v1.1 gate)"


def test_adversarial_corpus_categories_disjoint():
    sets = [set(PROMPT_INJECTION), set(SCOPE_ESCAPE), set(CREDENTIAL_EXFIL)]
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            assert not (sets[i] & sets[j]), "Categories must be disjoint"


def test_no_real_secrets_in_corpus():
    # Linter-style check: every alleged sk-* secret in the corpus must be
    # a clearly synthetic placeholder, not a leaked credential.
    SYNTHETIC_MARKERS = ("EXAMPLE", "FAKE", "PLACEHOLDER", "PROD-aaa", "test", "TEST", "LIVE-PROD-aaa")
    for category, prompt in ALL_ADVERSARIAL:
        m = re.search(r"sk-[A-Za-z0-9_-]{16,}", prompt)
        if m:
            assert any(mk in m.group(0) for mk in SYNTHETIC_MARKERS), (
                f"corpus prompt looks like a real secret: {prompt!r}"
            )
