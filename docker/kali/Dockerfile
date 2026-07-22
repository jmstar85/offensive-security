###############################################################################
# osa-kali base image — Kali coexistence v1 (PR-6).
#
# Reproducibility contract:
#   - Base pinned by digest:    kalilinux/kali-rolling@sha256:${KALI_DIGEST}
#   - Apt sources pinned via:   per-package version pins (KALI_APT_PKG_*),
#                               sourced from docker/kali/kali-apt-snapshot.env
#                               (PR-5.5 strategy).
#   - Non-root runtime user:    osa (uid 10001), WORKDIR /work (tmpfs at run).
#
# Build via `make build-kali` (loads both env files into the build args).
# `scripts/lint_kali_dockerfile.sh` enforces the FROM digest regex and the
# snapshot URL cross-reference. CODEOWNERS gates this file behind security-
# reviewer review (PR-7).
###############################################################################

ARG KALI_DIGEST
FROM kalilinux/kali-rolling@sha256:${KALI_DIGEST}

# Pinned apt package versions (sourced from docker/kali/kali-apt-snapshot.env).
ARG KALI_APT_PKG_GOBUSTER
ARG KALI_APT_PKG_SQLMAP
ARG KALI_APT_PKG_NIKTO
ARG KALI_APT_PKG_FFUF
ARG KALI_APT_REPO_URL

LABEL org.opencontainers.image.source="https://github.com/your-org/offensive-security" \
      org.opencontainers.image.title="osa-kali" \
      org.opencontainers.image.description="Hardened Kali base — gobuster/sqlmap/nikto" \
      org.opencontainers.image.licenses="GPL-3.0-or-later"

ENV DEBIAN_FRONTEND=noninteractive

# Install the v1 tool set with frozen versions. ca-certificates is required
# for https targets; everything else stays out via --no-install-recommends.
# Use the digest-pinned base image's own kali-rolling sources (deb822
# /etc/apt/sources.list.d/kali.sources). The legacy one-line
# `> /etc/apt/sources.list` overwrite conflicted with that on current base
# images ("configured multiple times" → empty index → apt exit 100). The repo
# origin stays deterministic via the KALI_DIGEST base pin (KALI_APT_REPO_URL is
# retained for provenance/audit but no longer rewrites sources).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         gobuster=${KALI_APT_PKG_GOBUSTER} \
         sqlmap=${KALI_APT_PKG_SQLMAP} \
         nikto=${KALI_APT_PKG_NIKTO} \
         ffuf=${KALI_APT_PKG_FFUF} \
         ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Read-only-friendly user + workdir. KaliBackend mounts tmpfs at /work and /tmp
# (read_only=True on the rootfs).
RUN useradd -u 10001 -m -s /bin/bash osa \
    && mkdir -p /work /wordlists \
    && chown -R osa:osa /work \
    && chmod 0755 /wordlists

USER osa
WORKDIR /work

ENTRYPOINT []
CMD ["/bin/bash", "-lc", "echo 'osa-kali base — invoke a specific tool binary via KaliExecAdapter.build_command()'"]
