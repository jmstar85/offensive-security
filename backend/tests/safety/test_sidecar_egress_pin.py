"""
Egress pinning assertions on docker-compose.yml for MF6 sidecar hardening.
Reads REPO_ROOT/docker-compose.yml; assumes W3 state with mitmproxy,
headless-browser, and interactsh services present.
"""
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

_ALLOWED_INTERACTSH_PORT_SUFFIXES = frozenset([
    "53/udp", "53/tcp", "80", "443", "8443",
    ":53/udp", ":53/tcp", ":80", ":443", ":8443",
])

_OSA_DIGEST_RE = re.compile(r"^OSA_[A-Z_]+_DIGEST$")


def _load_compose():
    import yaml
    with open(COMPOSE_FILE) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def compose():
    return _load_compose()


def _port_strings(service_data):
    raw = service_data.get("ports", [])
    return [str(p) for p in raw]


def test_mitmproxy_does_not_publish_extra_ports(compose):
    allowed = {"8080:8080", "8081:8081"}
    ports = set(_port_strings(compose["services"]["mitmproxy"]))
    extra = ports - allowed
    assert not extra, (
        f"mitmproxy publishes unexpected ports: {extra!r}; allowed: {allowed!r}"
    )


def test_headless_browser_does_not_publish_extra_ports(compose):
    ports = _port_strings(compose["services"]["headless-browser"])
    assert ports == [], (
        f"headless-browser must not publish any host ports, got: {ports!r}"
    )


def test_interactsh_only_publishes_oob_protocol_ports(compose):
    ports = _port_strings(compose["services"]["interactsh"])
    for p in ports:
        # Accept mappings like "53:53/udp", "0.0.0.0:443:443", ":8443:8443"
        # Extract the container-side portion which includes the protocol suffix.
        # Format: [host:]container[/protocol]
        container_side = p.split(":")[-1]
        matched = any(
            container_side.endswith(suffix.lstrip(":"))
            for suffix in _ALLOWED_INTERACTSH_PORT_SUFFIXES
        )
        assert matched, (
            f"interactsh publishes unexpected port {p!r}; "
            f"only OOB protocol ports (53/udp,53/tcp,80,443,8443) are allowed"
        )


def test_no_sidecar_mounts_docker_sock(compose):
    sidecars = ["mitmproxy", "headless-browser", "interactsh"]
    services = compose["services"]
    for name in sidecars:
        if name not in services:
            continue
        volumes = services[name].get("volumes", [])
        for v in volumes:
            assert "/var/run/docker.sock" not in str(v), (
                f"Sidecar '{name}' must not mount /var/run/docker.sock, "
                f"found volume: {v!r}"
            )


def test_sidecar_images_digest_pinnable(compose):
    sidecars = ["mitmproxy", "headless-browser", "interactsh"]
    services = compose["services"]
    for name in sidecars:
        if name not in services:
            continue
        svc = services[name]
        build_cfg = svc.get("build", {})
        if isinstance(build_cfg, str):
            # bare context path — no build.args to check
            continue
        build_args = build_cfg.get("args", {})
        if isinstance(build_args, list):
            arg_names = []
            for item in build_args:
                arg_names.append(item.split("=", 1)[0] if "=" in item else item)
        else:
            arg_names = list(build_args.keys()) if build_args else []
        has_digest_arg = any(_OSA_DIGEST_RE.match(k) for k in arg_names)
        assert has_digest_arg, (
            f"Sidecar '{name}' build.args must contain at least one "
            f"OSA_*_DIGEST ARG for digest pinning, found args: {arg_names!r}"
        )
