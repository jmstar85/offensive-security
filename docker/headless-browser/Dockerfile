# syntax=docker/dockerfile:1
# Headless browser sidecar — XBOW DOM/JS vector observation (W3/PR3.1).
#
# SF5 rationale: Playwright with chromium-headless is the de-facto
# standard for DOM-XSS/CSRF probes; reusing the official base avoids
# us shipping a chromium toolchain.
#
ARG OSA_HEADLESS_DIGEST=sha256:0000000000000000000000000000000000000000000000000000000000000000
FROM mcr.microsoft.com/playwright@${OSA_HEADLESS_DIGEST} AS base

RUN useradd -m -u 1001 osa
USER osa
WORKDIR /work
COPY harness/ /home/osa/harness/
EXPOSE 9222

ENTRYPOINT ["node", "/home/osa/harness/probe_runner.js"]
