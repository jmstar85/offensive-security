"""Availability guards must skip connection failures, not SDK defects."""
from unittest.mock import MagicMock

import docker
import pytest
from docker.errors import DockerException
from requests.exceptions import ConnectionError as DockerConnectionError, Timeout


@pytest.mark.parametrize("cause", [DockerConnectionError(), Timeout()])
def test_docker_guard_skips_unavailable_daemon(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest, cause: Exception,
) -> None:
    failure = DockerException()
    failure.__cause__ = cause
    monkeypatch.setattr(docker, "from_env", MagicMock(side_effect=failure))

    with pytest.raises(pytest.skip.Exception):
        request.getfixturevalue("require_docker_daemon")


@pytest.mark.parametrize("cause", [None, ValueError()])
def test_docker_guard_propagates_non_connection_errors(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest,
    cause: Exception | None,
) -> None:
    failure = DockerException()
    failure.__cause__ = cause
    monkeypatch.setattr(docker, "from_env", MagicMock(side_effect=failure))

    with pytest.raises(DockerException) as raised:
        request.getfixturevalue("require_docker_daemon")

    assert raised.value is failure


def test_docker_guard_closes_probe_when_daemon_available(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest,
) -> None:
    client = MagicMock()
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(docker, "from_env", factory)

    request.getfixturevalue("require_docker_daemon")

    factory.assert_called_once_with(timeout=2)
    client.close.assert_called_once_with()
