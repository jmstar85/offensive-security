#!/usr/bin/env bash
# Build all OSA Docker images.
# Usage: ./ci/build-images.sh [--push] [--tag <suffix>]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

TAG="${OSA_IMAGE_TAG:-latest}"
PUSH=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --push)  PUSH=true; shift ;;
        --tag)   TAG="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--push] [--tag <suffix>]"
            exit 0
            ;;
        *)       echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

echo "==> Building osa-passive-recon:${TAG}"
docker build -t "osa-passive-recon:${TAG}" -f docker/passive-recon/Dockerfile .

declare -A AGENT_IMAGES=(
    ["osa-agent-subfinder"]="docker/agents/Dockerfile.subfinder"
    ["osa-agent-dnsx"]="docker/agents/Dockerfile.dnsx"
    ["osa-agent-httpx"]="docker/agents/Dockerfile.httpx"
    ["osa-agent-cloudenum"]="docker/agents/Dockerfile.cloudenum"
    ["osa-agent-wappalyzer"]="docker/agents/Dockerfile.wappalyzer"
    ["osa-agent-katana"]="docker/agents/Dockerfile.katana"
    ["osa-agent-zap"]="docker/agents/Dockerfile.zap"
)

for name in "${!AGENT_IMAGES[@]}"; do
    df="${AGENT_IMAGES[$name]}"
    echo "==> Building ${name}:${TAG} from ${df}"
    docker build -t "${name}:${TAG}" -f "$df" .
done

if $PUSH; then
    : "${OSA_REGISTRY:?OSA_REGISTRY must be set when --push is used}"
    for name in osa-passive-recon "${!AGENT_IMAGES[@]}"; do
        target="${OSA_REGISTRY}/${name}:${TAG}"
        echo "==> Tagging + pushing ${target}"
        docker tag "${name}:${TAG}" "$target"
        docker push "$target"
    done
fi

echo "==> All images built ($(date -u +%FT%TZ))"
