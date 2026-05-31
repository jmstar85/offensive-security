# syntax=docker/dockerfile:1
# MITM proxy sidecar — XBOW vector enrichment (W3/PR3.1).
#
# SF5 (reuse-first rejection rationale): mitmproxy is the canonical
# in-process HTTPS interception toolkit; the upstream image already
# ships with the addon hook system we need. Rebuilding from scratch
# would force us to re-implement WebSocket+HTTP2 framing — no benefit.
#
# Digest pin: tag is intentionally a placeholder; the quarterly
# OSA_OSA_MITMPROXY_DIGEST refresh workflow updates ARG OSA_MITMPROXY_DIGEST
# below and rebuilds.
ARG OSA_MITMPROXY_DIGEST=sha256:0000000000000000000000000000000000000000000000000000000000000000
FROM mitmproxy/mitmproxy@${OSA_MITMPROXY_DIGEST} AS base

USER root
RUN mkdir -p /work /addons && chown -R mitmproxy:mitmproxy /work /addons
USER mitmproxy

COPY addons/ /addons/
ENV MITM_ADDON_DIR=/addons
EXPOSE 8080 8081

ENTRYPOINT ["mitmdump", "-s", "/addons/osa_addon.py", "--mode", "regular"]
