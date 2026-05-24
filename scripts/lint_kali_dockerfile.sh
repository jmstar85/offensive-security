#!/usr/bin/env bash
# Enforce the PR-6 reproducibility contract on docker/kali/Dockerfile.
#
# Checks:
#   1. The Dockerfile's first FROM line uses a sha256-pinned kali-rolling image.
#   2. The Dockerfile references ${KALI_APT_REPO_URL} and the per-package
#      ARGs defined in docker/kali/kali-apt-snapshot.env (no drift).
#
# Exits non-zero on any violation. Designed to run inside CI without docker.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKERFILE="${REPO_ROOT}/docker/kali/Dockerfile"
APT_ENV="${REPO_ROOT}/docker/kali/kali-apt-snapshot.env"

fail() {
  echo "lint_kali_dockerfile: FAIL — $*" >&2
  exit 1
}

[ -f "${DOCKERFILE}" ] || fail "missing ${DOCKERFILE}"
[ -f "${APT_ENV}" ]    || fail "missing ${APT_ENV}"

# 1. FROM line must pin by digest.
first_from="$(grep -E '^FROM ' "${DOCKERFILE}" | head -1)"
[ -n "${first_from}" ] || fail "no FROM line found"
expected_rx='^FROM kalilinux/kali-rolling@sha256:\$\{KALI_DIGEST\}$'
if ! echo "${first_from}" | grep -Eq "${expected_rx}"; then
  fail "FROM line must match ${expected_rx} (got: ${first_from})"
fi

# 2. Snapshot URL + per-package ARGs cross-reference.
required_args=(
  KALI_APT_REPO_URL
  KALI_APT_PKG_GOBUSTER
  KALI_APT_PKG_SQLMAP
  KALI_APT_PKG_NIKTO
)
for var in "${required_args[@]}"; do
  grep -Eq "^ARG ${var}\$" "${DOCKERFILE}" \
    || fail "Dockerfile missing ARG ${var}"
  grep -Eq "^${var}=" "${APT_ENV}" \
    || fail "${APT_ENV} missing ${var}="
done

# Dockerfile must inject the repo URL into apt sources.
grep -q '${KALI_APT_REPO_URL}' "${DOCKERFILE}" \
  || fail "Dockerfile must reference \${KALI_APT_REPO_URL} in the apt sources line"

echo "lint_kali_dockerfile: OK"
