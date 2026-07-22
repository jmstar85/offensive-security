# OWASP ZAP — the canonical OWASP DAST scanner (baseline: spider + passive rules).
# Tier=active_recon. The adapter emits zap-baseline.py ARGS (ZapAdapter.build_command);
# the console summary (WARN-NEW/FAIL-NEW) is parsed by parse_output.
FROM ghcr.io/zaproxy/zaproxy:stable
ENTRYPOINT ["zap-baseline.py"]
