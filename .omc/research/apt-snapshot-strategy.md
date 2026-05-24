# Apt snapshot strategy for the Kali coexistence base image

**Status:** decision recorded — PR-5.5 gate for PR-6.
**Owner:** kali coexistence v1.
**Date:** 2026-05-24.

## Question

The Kali base image (PR-6) needs reproducibility on the apt layer as well
as the image layer. `kalilinux/kali-rolling@sha256:<digest>` pins the
*base*, but `apt-get update && apt-get install gobuster sqlmap nikto`
inside the Dockerfile floats unless the apt sources and per-package
versions are pinned to a fixed point in time.

Three candidate strategies were considered.

## Findings

### (a) snapshot.debian.org

`snapshot.debian.org` only mirrors Debian. It does **not** mirror Kali
rolling. The DSA archive does carry some Kali sources for the security
research community, but it is not a usable apt source for a Kali
container build. **Rejected.**

### (b) Kali official archive (`http.kali.org` / `archive.kali.org`)

Kali distributes through `http.kali.org` (round-robin to community
mirrors) and keeps an archive at `archive.kali.org`. Kali does not run a
`snapshot.debian.org`-equivalent service with per-day URLs, but two
properties of the Kali pool make stable pinning possible:

1. Each binary `.deb` lives at a deterministic, version-named URL under
   `pool/main/<letter>/<source>/<binary>_<version>_amd64.deb`. Once
   published, those filenames are stable.
2. Quarterly Kali point releases (`kali-2026.1`, etc.) produce a frozen
   set of package versions in `dists/kali-rolling/Release` at the
   release timestamp — that timestamp can be quoted in the `Release`
   file's `Valid-Until` field.

The pragmatic v1 strategy is therefore: **pin per-package versions** in
the Dockerfile (`apt-get install -y gobuster=<ver> sqlmap=<ver>
nikto=<ver>`) and lock the Kali pool URL + the per-package SHA-256s in
`docker/kali/kali-apt-snapshot.env`. CI verifies that the pinned versions are still
fetchable on rebuild; if Kali ever rotates them out of the live pool the
quarterly-rebuild workflow alerts and we either re-pin to the next
version (with security-reviewer sign-off, A3.6) or restore the rotated
`.deb` from our SBOM-tracked cache.

**Selected — primary v1 strategy.**

### (c) Self-hosted apt mirror

A self-hosted mirror (aptly + S3/R2) gives us byte-for-byte reproduction
even when Kali rotates packages, at the cost of additional infrastructure
ownership. v1 keeps this as the **failure-mode fallback** documented in
the runbook: if quarterly CI ever observes that >=2 of the 3 v1 tools
have been pulled from the upstream pool in a single quarter, we stand up
an aptly mirror and switch `KALI_APT_REPO_URL` to point at it.

## Decision

v1 ships with strategy (b): per-package version pinning against the live
Kali pool, with per-package SHA-256 locks in `docker/kali/kali-apt-snapshot.env`.
PR-6 implements the Dockerfile and the lint script that enforces the
pin format and the snapshot/Dockerfile cross-reference.

## Failure-mode discussion

- **Upstream rotation.** Quarterly CI rebuild will surface this via the
  apt-snapshot diff alarm. If just one tool is affected we re-pin under
  security-reviewer review; if multiple are affected we activate (c) the
  self-hosted mirror per the runbook.
- **Pool URL change.** `KALI_APT_REPO_URL` is parameterised in
  `docker/kali/kali-apt-snapshot.env`; runbook documents the rotation procedure.
- **Hash mismatch on build.** Build fails closed — the per-package
  SHA-256 lock guarantees byte-for-byte reproducibility.

## `docker/kali/kali-apt-snapshot.env` schema (consumed by PR-6)

```
# Repository base — round-robin Kali mirror.
KALI_APT_REPO_URL=https://http.kali.org/kali

# Pinning anchor for diff/audit. Treat as informational; actual reproducibility
# is enforced by KALI_APT_PACKAGES_LOCK_SHA256 below.
KALI_APT_SNAPSHOT_DATE=2026-05-01

# Frozen package versions installed in the Kali base image (consumed by the
# Dockerfile `apt-get install -y` line; updates require security-reviewer
# approval via CODEOWNERS on `.env.kali*`).
KALI_APT_PKG_GOBUSTER=3.6-1kali1
KALI_APT_PKG_SQLMAP=1.8.2-1kali1
KALI_APT_PKG_NIKTO=1:2.5.0-1kali1

# SHA-256 of the concatenated (filename || size || sha256) of each pinned
# .deb file. Computed by `make build-kali` and checked into git.
KALI_APT_PACKAGES_LOCK_SHA256=<filled-by-PR-6>
```

## Example PR-6 Dockerfile snippet

```dockerfile
ARG KALI_DIGEST
FROM kalilinux/kali-rolling@sha256:${KALI_DIGEST}

ARG KALI_APT_PKG_GOBUSTER
ARG KALI_APT_PKG_SQLMAP
ARG KALI_APT_PKG_NIKTO

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         gobuster=${KALI_APT_PKG_GOBUSTER} \
         sqlmap=${KALI_APT_PKG_SQLMAP} \
         nikto=${KALI_APT_PKG_NIKTO} \
         ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -u 10001 -m -s /bin/bash osa \
    && mkdir -p /work \
    && chown osa:osa /work
USER osa
WORKDIR /work
```
