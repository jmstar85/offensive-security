"""PassiveReconAdapter — runs the shared osa-passive-recon image with a
specific entrypoint and JSON args payload.

Plan v3.2.1 §2.2: the shared image hosts 7+ entrypoints (secret_scan,
dns_resolver, cert_transparency, mx_spf_dmarc, robots_sitemap, well_known,
securitytxt, cert_chain).
"""
from __future__ import annotations

import json
import shlex

from app.agents.base import AgentAdapter, AgentResult, RiskLevel
from app.core.config import settings


class PassiveReconAdapter(AgentAdapter):
    agent_type = "passive_recon"
    docker_image = settings.passive_recon_image
    risk_level = RiskLevel.LOW

    def get_capabilities(self) -> list[str]:
        return [
            "secret_scan",
            "dns_resolver",
            "cert_transparency",
            "mx_spf_dmarc",
            "robots_sitemap",
            "well_known",
            "securitytxt",
            "cert_chain",
        ]

    def build_command(self, target: dict, config: dict) -> list[str]:
        entry = config.get("entrypoint", "dns_resolver")
        args: list[str] = []
        for k, v in config.get("args", {}).items():
            args.append(f"--{k}")
            args.append(str(v))
        if not args and target.get("domains"):
            args.extend(["--domain", target["domains"][0]])
        return [entry, *args]

    def parse_output(self, raw_output: str) -> AgentResult:
        findings: list[dict] = []
        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                findings.append(json.loads(line))
            except json.JSONDecodeError:
                findings.append({"line": line})
        return AgentResult(
            agent_type=self.agent_type,
            success=True,
            findings=findings,
            raw_output=raw_output,
        )

    @staticmethod
    def _quote_args(args: list[str]) -> str:
        return " ".join(shlex.quote(a) for a in args)
