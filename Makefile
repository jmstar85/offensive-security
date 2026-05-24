# Project Makefile — currently scoped to the Kali coexistence v1 deliverables.
# Additional targets land here over time; keep them small and one-purpose.

SHELL := /usr/bin/env bash

KALI_ENV         := docker/kali/kali.env
KALI_APT_ENV     := docker/kali/kali-apt-snapshot.env
KALI_DOCKERFILE  := docker/kali/Dockerfile
KALI_SBOM_DIR    := .omc/sbom

.PHONY: help lint-kali build-kali

help:
	@echo "Targets:"
	@echo "  lint-kali   — run scripts/lint_kali_dockerfile.sh"
	@echo "  build-kali  — build osa-kali image + emit SBOM to $(KALI_SBOM_DIR)/"

lint-kali:
	bash scripts/lint_kali_dockerfile.sh

# Builds the hardened Kali base image with all reproducibility pins applied,
# then emits an SBOM to .omc/sbom/kali-base-<digest>-<UTC-date>.json. The SBOM
# step prefers syft; falls back to `docker sbom`; fails closed if neither is
# installed (do NOT silently skip — Principle 3: reproducibility before
# convenience).
build-kali: lint-kali
	@set -euo pipefail; \
	source $(KALI_ENV); \
	source $(KALI_APT_ENV); \
	if [ -z "$${KALI_DIGEST:-}" ]; then \
	  echo "build-kali: KALI_DIGEST not set in $(KALI_ENV)" >&2; exit 2; \
	fi; \
	TAG_DIGEST="osa-kali:$${KALI_DIGEST:0:12}"; \
	echo "build-kali: building $$TAG_DIGEST"; \
	docker build \
	  --build-arg KALI_DIGEST=$${KALI_DIGEST} \
	  --build-arg KALI_APT_REPO_URL=$${KALI_APT_REPO_URL} \
	  --build-arg KALI_APT_PKG_GOBUSTER=$${KALI_APT_PKG_GOBUSTER} \
	  --build-arg KALI_APT_PKG_SQLMAP=$${KALI_APT_PKG_SQLMAP} \
	  --build-arg KALI_APT_PKG_NIKTO=$${KALI_APT_PKG_NIKTO} \
	  -t osa-kali:latest -t $$TAG_DIGEST \
	  -f $(KALI_DOCKERFILE) .; \
	mkdir -p $(KALI_SBOM_DIR); \
	SBOM_PATH="$(KALI_SBOM_DIR)/kali-base-$${KALI_DIGEST:0:12}-$$(date -u +%Y%m%d).json"; \
	if command -v syft >/dev/null 2>&1; then \
	  syft "osa-kali:latest" -o spdx-json="$$SBOM_PATH"; \
	elif docker sbom --help >/dev/null 2>&1; then \
	  docker sbom --format spdx-json -o "$$SBOM_PATH" osa-kali:latest; \
	else \
	  echo "build-kali: neither syft nor 'docker sbom' available — install one" >&2; \
	  exit 3; \
	fi; \
	echo "build-kali: SBOM written to $$SBOM_PATH"; \
	echo "build-kali: image size:"; \
	docker image inspect osa-kali:latest --format '  {{.Size}} bytes'
