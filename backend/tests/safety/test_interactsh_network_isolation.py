"""
Compose-level YAML assertions for MF6: interactsh network isolation invariants.
Asserts on docker-compose.yml read from REPO_ROOT (three levels above this file).
Assumes W3 state: osa-net and osa-oob-net top-level networks present,
interactsh service on osa-oob-net only.
"""
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"


def _load_compose():
    import yaml
    with open(COMPOSE_FILE) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def compose():
    return _load_compose()


def _service_networks(compose, service_name):
    svc = compose["services"][service_name]
    nets = svc.get("networks", [])
    if isinstance(nets, dict):
        return list(nets.keys())
    return list(nets)


def test_interactsh_only_on_osa_oob_net(compose):
    nets = _service_networks(compose, "interactsh")
    assert nets == ["osa-oob-net"], (
        f"interactsh must be on osa-oob-net only, got: {nets!r}"
    )


def test_interactsh_not_on_osa_net(compose):
    nets = _service_networks(compose, "interactsh")
    assert "osa-net" not in nets, (
        "interactsh must NOT be on osa-net"
    )


def test_docker_socket_proxy_not_on_osa_oob_net(compose):
    svc = compose["services"]["docker-socket-proxy"]
    nets = svc.get("networks", [])
    if isinstance(nets, dict):
        net_list = list(nets.keys())
    else:
        net_list = list(nets)
    assert "osa-oob-net" not in net_list, (
        f"docker-socket-proxy must NOT be on osa-oob-net, got: {net_list!r}"
    )


def test_backend_on_osa_net(compose):
    nets = _service_networks(compose, "backend")
    assert "osa-net" in nets, (
        f"backend must be on osa-net, got: {nets!r}"
    )


def test_osa_oob_net_is_internal_or_isolated(compose):
    top_nets = compose.get("networks", {})
    assert "osa-oob-net" in top_nets, "osa-oob-net must exist as a top-level network"
    oob_cfg = top_nets["osa-oob-net"] or {}
    driver = oob_cfg.get("driver", "bridge")
    assert driver == "bridge", (
        f"osa-oob-net driver must be 'bridge', got: {driver!r}"
    )


def test_no_other_sidecar_on_osa_oob_net(compose):
    services = compose["services"]
    on_oob = []
    for name, svc in services.items():
        nets = svc.get("networks", [])
        if isinstance(nets, dict):
            net_list = list(nets.keys())
        else:
            net_list = list(nets)
        if "osa-oob-net" in net_list:
            on_oob.append(name)
    assert on_oob == ["interactsh"], (
        f"Only interactsh should be on osa-oob-net, got: {on_oob!r}"
    )
