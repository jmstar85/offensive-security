"""
Compose-lint: assert v1.1 baseline invariants on docker-compose.yml.
All assertions read the file relative to the repo root (two levels above backend/).
"""
import os
import re
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"


def _load_compose():
    try:
        import yaml
        with open(COMPOSE_FILE) as f:
            return yaml.safe_load(f)
    except ImportError:
        # fallback: minimal regex-based parse not needed — yaml ships with the venv
        raise RuntimeError("PyYAML not available")


@pytest.fixture(scope="module")
def compose():
    return _load_compose()


def _env(service_data):
    """Return environment as a dict regardless of list or mapping form."""
    env = service_data.get("environment", {})
    if isinstance(env, list):
        result = {}
        for item in env:
            if "=" in item:
                k, v = item.split("=", 1)
            else:
                k, v = item, ""
            result[k] = v
        return result
    return {str(k): str(v) for k, v in env.items()}


def test_docker_socket_proxy_env_tuple(compose):
    svc = compose["services"]["docker-socket-proxy"]
    env = _env(svc)
    assert env.get("CONTAINERS") == "1", "CONTAINERS must be 1"
    assert env.get("POST") == "1", "POST must be 1"
    for key in ("IMAGES", "NETWORKS", "VOLUMES", "EXEC", "INFO",
                "SERVICES", "SWARM", "SYSTEM", "TASKS", "BUILD"):
        assert env.get(key) == "0", f"{key} must be 0"


def test_docker_socket_proxy_ro_socket_mount(compose):
    svc = compose["services"]["docker-socket-proxy"]
    volumes = svc.get("volumes", [])
    assert any(
        str(v) == "/var/run/docker.sock:/var/run/docker.sock:ro"
        for v in volumes
    ), "docker-socket-proxy must mount docker.sock as :ro"


def test_backend_keeps_host_socket_mount(compose):
    svc = compose["services"]["backend"]
    volumes = svc.get("volumes", [])
    assert any(
        str(v) == "/var/run/docker.sock:/var/run/docker.sock"
        for v in volumes
    ), "backend must keep direct /var/run/docker.sock mount (Principle 5)"


def test_backend_kali_docker_host_env_present(compose):
    svc = compose["services"]["backend"]
    env = _env(svc)
    val = env.get("KALI_DOCKER_HOST", "")
    assert val == "tcp://kali-socket-proxy-filter:2375", (
        f"KALI_DOCKER_HOST must point at kali-socket-proxy-filter, got: {val!r}"
    )


def test_tecnativa_proxy_digest_pinned(compose):
    svc = compose["services"]["docker-socket-proxy"]
    image = svc.get("image", "")
    pattern = r"^tecnativa/docker-socket-proxy@sha256:[a-f0-9]{64}$"
    assert re.match(pattern, image), (
        f"docker-socket-proxy image must be digest-pinned, got: {image!r}"
    )


def test_baseline_network_membership_compose_v1_1(compose):
    services = compose.get("services", {})
    backend_svc = services.get("backend", {})
    assert "networks" not in backend_svc, (
        "At v1.1 baseline, backend service must NOT have a 'networks:' key "
        "(uses default network; osa-oob-net is added in W3)"
    )
    top_level_networks = compose.get("networks", {})
    assert "osa-oob-net" not in top_level_networks, (
        "osa-oob-net must not exist yet at v1.1 baseline (added in W3)"
    )
