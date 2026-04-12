"""Risk assessor and filter — scores attack plans and blocks critical-risk steps."""
from __future__ import annotations

from app.agents.base import RiskLevel

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
