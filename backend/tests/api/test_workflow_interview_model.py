"""PR4 — per-provider interview/chat model resolution (Blocking 1 / PM3).

The interview/chat turn must be DECOUPLED from ``session.model_id`` (never
promoted to the opus-4-8 session default) and coherent with the interview
PROVIDER, so an Ollama-only session never receives an Anthropic id
("Ollama never prompts").
"""
from types import SimpleNamespace

from app.core.config import settings
from app.orchestrator.workflow_service import (
    WorkflowService,
    resolve_interview_model,
)


def _session(provider, model_id="claude-opus-4-8"):
    return SimpleNamespace(llm_provider_pref=provider, model_id=model_id)


# ── per-provider interview model (decoupled from session.model_id) ──────────


def test_anthropic_session_interview_resolves_sonnet_not_opus():
    # session.model_id is opus-4-8, but the interview turn must resolve to the
    # cheaper sonnet-4-6 for an anthropic provider — never promoted to opus.
    session = _session("anthropic", model_id="claude-opus-4-8")
    assert resolve_interview_model(session) == "claude-sonnet-4-6"
    assert resolve_interview_model(session) == settings.anthropic_default_model
    assert resolve_interview_model(session) != "claude-opus-4-8"


def test_ollama_session_interview_resolves_qwen_never_anthropic_id():
    # Blocking 1: an ollama session resolves the interview MODEL to the local
    # qwen model and NEVER yields an Anthropic id (garbage to OllamaClient).
    session = _session("ollama", model_id="claude-opus-4-8")
    resolved = resolve_interview_model(session)
    assert resolved == "qwen3-14b-96k:latest"
    assert resolved == settings.ollama_model
    assert not resolved.startswith("claude-")


def test_openai_session_interview_resolves_cheap_gpt():
    session = _session("openai", model_id="claude-opus-4-8")
    assert resolve_interview_model(session) == "gpt-4o-mini"
    assert resolve_interview_model(session) == settings.openai_interview_model


def test_null_provider_falls_back_to_global_switch_default():
    # NULL llm_provider_pref → settings.osa_llm_provider cheap default
    # (anthropic ⇒ sonnet-4-6) so legacy interview behavior is byte-identical.
    session = _session(None, model_id="claude-opus-4-8")
    if settings.osa_llm_provider == "ollama":
        assert resolve_interview_model(session) == settings.ollama_model
    elif settings.osa_llm_provider == "openai":
        assert resolve_interview_model(session) == settings.openai_interview_model
    else:
        assert resolve_interview_model(session) == "claude-sonnet-4-6"
        assert resolve_interview_model(session) == settings.anthropic_default_model


# ── copilot honors the operator-selected model (user requirement) ───────────


def test_copilot_session_interview_honors_selected_model():
    # Unlike the cheap-default providers above, a Copilot session runs the
    # interview on the SPECIFIC model the operator selected from the catalog.
    session = _session("copilot", model_id="copilot/claude-sonnet-4.6")
    assert resolve_interview_model(session) == "copilot/claude-sonnet-4.6"


def test_copilot_session_interview_falls_back_when_unset_or_incoherent():
    default = getattr(settings, "github_copilot_default_model", "copilot/gpt-4o")
    # No selection → the per-provider default.
    assert resolve_interview_model(_session("copilot", model_id=None)) == default
    # A non-Copilot-namespaced id is not a valid Copilot model → default.
    assert (
        resolve_interview_model(_session("copilot", model_id="claude-opus-4-8"))
        == default
    )


# ── _resolved_anthropic_id opus-4-8 branch ──────────────────────────────────


def test_resolved_anthropic_id_opus_4_8_branch():
    svc = WorkflowService(db=None)
    assert svc._resolved_anthropic_id("claude-opus-4-8") == "claude-opus-4-8"
    assert (
        svc._resolved_anthropic_id("claude-opus-4-8")
        == settings.session_default_model_anthropic_id
    )
