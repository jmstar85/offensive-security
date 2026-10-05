"""Unit-test guards for the few registry checks using a real Docker daemon."""
from contextlib import closing

import docker
import pytest
from docker.errors import DockerException
from requests.exceptions import ConnectionError as DockerConnectionError, Timeout


@pytest.fixture
def require_docker_daemon() -> None:
    """Probe the configured endpoint without hiding non-connection failures.

    from_env negotiates the server API version, so remote daemons are supported
    without assuming a fixed local socket path.
    """
    try:
        with closing(docker.from_env(timeout=2)):
            pass
    except DockerException as exc:
        if not isinstance(exc.__cause__, (DockerConnectionError, Timeout)):
            raise
        pytest.skip(f"Docker daemon unavailable: {exc}")
