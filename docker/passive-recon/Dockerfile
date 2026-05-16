FROM python:3.12-slim AS base
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        dnsutils \
        iptables \
    && rm -rf /var/lib/apt/lists/*

COPY docker/passive-recon/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY docker/passive-recon/lib /app/lib
COPY docker/passive-recon/entrypoints /app/entrypoints
COPY docker/passive-recon/run.sh /app/run.sh
RUN chmod +x /app/run.sh

ENV PYTHONUNBUFFERED=1
ENV OSA_TIER=passive

# Egress lockdown is enforced at runtime via /app/lib/allowlist_transport.py
# and by the orchestrator's per-container network policy.
ENTRYPOINT ["/app/run.sh"]
