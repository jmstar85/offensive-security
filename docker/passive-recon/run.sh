#!/usr/bin/env bash
# osa-passive-recon multi-entrypoint dispatcher.
# Usage: docker run --rm osa-passive-recon:latest <entrypoint> [args...]
# Available entrypoints:
#   secret_scan, dns_resolver, cert_transparency, mx_spf_dmarc,
#   robots_sitemap, well_known, securitytxt, cert_chain
set -euo pipefail

ENTRY="${1:-help}"
shift || true

case "$ENTRY" in
    help|--help|-h)
        echo "osa-passive-recon entrypoints:"
        ls /app/entrypoints/ | sed 's/\.py$//' | sed 's/^/  /'
        exit 0
        ;;
    secret_scan|dns_resolver|cert_transparency|mx_spf_dmarc|robots_sitemap|well_known|securitytxt|cert_chain)
        exec python -m entrypoints."$ENTRY" "$@"
        ;;
    *)
        echo "unknown entrypoint: $ENTRY" >&2
        exit 2
        ;;
esac
