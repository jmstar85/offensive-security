"""Risk assessor and filter — scores attack plans and blocks critical-risk steps.

Plan v3.2.1 §2.4: TIER_RISK is the **canonical** source of base risk; legacy
``_AGENT_BASE_RISK`` is retained only for tools that have not yet been tier-tagged
in ``app.agents.registry``. ``base_risk_for_slug`` consults the registry first
and falls back to the legacy map.

This file extends the safety chain — it does NOT change the meaning of
``filter_steps`` or ``score_plan`` for existing tools, so all existing
TestRiskFilter assertions keep passing.
"""
from __future__ import annotations

from app.agents.base import RiskLevel

# Tier → numeric base-risk weight (plan v3.2.1 §2.4)
TIER_RISK: dict[str, float] = {
    "passive_no_target_contact": 0.05,
    "passive_low_touch": 0.30,
    "active_recon": 0.55,
    "active_exploit": 0.85,
}

_AGENT_BASE_RISK = {
    "nmap": 0.1,
    "nuclei": 0.4,
    "metasploit": 0.8,
    "pyrit": 0.3,
}

_BLOCKED_ACTIONS = {
    "dos", "ddos", "ransomware", "wiper", "data_destruction",
    "rm -rf", "format", "drop table", "truncate",
}


def tier_risk(tier: str) -> float:
    """Return the numeric base-risk weight for a tier."""
    if tier not in TIER_RISK:
        raise ValueError(f"Unknown tier: {tier}")
    return TIER_RISK[tier]


def base_risk_for_slug(slug: str) -> float:
    """Return base risk for a tool slug.

    Prefers the registry's tier-derived value (plan v3.2.1); falls back to the
    legacy per-agent map for tools that predate the tier system.
    """
    try:
        from app.agents.registry import get_tier
    except ImportError:  # avoid hard dep during early import paths
        get_tier = lambda _: None  # noqa: E731

    tier = get_tier(slug)
    if tier is not None:
        return TIER_RISK[tier]
    return _AGENT_BASE_RISK.get(slug, 0.5)


class RiskFilter:
    def assess_step(self, step: dict) -> RiskLevel:
        agent = step.get("agent", "")
        action = step.get("action", "").lower()
        base = _AGENT_BASE_RISK.get(agent, 0.5)

        # Bump risk for known destructive keywords in action description
        if any(blocked in action for blocked in _BLOCKED_ACTIONS):
            return RiskLevel.CRITICAL

        if base >= 0.8:
            return RiskLevel.HIGH
        if base >= 0.4:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def filter_steps(self, steps: list[dict]) -> tuple[list[dict], list[dict]]:
        """Returns (allowed_steps, blocked_steps)."""
        allowed, blocked = [], []
        for step in steps:
            level = self.assess_step(step)
            if level == RiskLevel.CRITICAL:
                blocked.append({**step, "blocked_risk": level.value})
            else:
                allowed.append(step)
        return allowed, blocked

    def score_plan(self, steps: list[dict]) -> float:
        """Returns an overall risk score 0.0–10.0."""
        if not steps:
            return 0.0
        scores = [_AGENT_BASE_RISK.get(s.get("agent", ""), 0.5) for s in steps]
        return round(min(10.0, max(scores) * 10), 1)
