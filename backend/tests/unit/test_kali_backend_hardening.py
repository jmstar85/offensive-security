"""KaliBackend.start() hardening contract — mock-based verification.

Per the consensus plan (ralplan-kali-coexistence-v1.md §A1.2), every
KaliBackend.start() call MUST pass the following kwargs to docker-py
`containers.create()` (start() is called separately so a failed start does not
leak a "created"-state zombie container):

  - security_opt = ["no-new-privileges:true"]  (+ docker's implicit default seccomp)
  - cap_drop     = ["ALL"]
  - cap_add      = ⊆ KALI_ALLOWED_CAPS   (frozenset() in v1)
  - read_only    = True
  - tmpfs        = {"/tmp": "size=128m,mode=1777",
                    "/work": "size=512m,mode=1777"}
  - network_disabled = (network is None)
  - mem_limit/cpu_quota/pids_limit honored from resource_limits

We also enforce Principle 5: KaliBackend MUST NOT be a subclass of
DockerBackend (sibling pattern).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agents.backends.docker import DockerBackend
from app.agents.backends.kali import (
    KALI_SECURITY_OPT,
    KALI_TMPFS,
    KaliBackend,
)
from app.agents.base import ExecutionBackend
from app.agents.kali_whitelist import SafetyViolation


# ---------------------------------------------------------------- structural

def test_kali_backend_is_execution_backend_subclass() -> None:
    assert issubclass(KaliBackend, ExecutionBackend)


def test_kali_backend_is_not_docker_backend_subclass() -> None:
    # Principle 5 — sibling, not subclass. Hardening must not inject into
    # the legacy DockerBackend path.
    assert not issubclass(KaliBackend, DockerBackend)


def test_kali_backend_has_isolated_docker_client() -> None:
    # PR-7: KaliBackend uses docker.DockerClient(base_url=...) and
    # DockerBackend keeps docker.from_env() — separate clients by construction.
    with patch("app.agents.backends.kali.docker.DockerClient") as kali_dc, \
         patch("docker.from_env") as from_env:
        kali_dc.return_value = MagicMock(name="kali-client")
        from_env.return_value = MagicMock(name="docker-client")
        kb = KaliBackend()
        db = DockerBackend()
    assert kb._client is not db._client
    assert kali_dc.call_count == 1
    assert from_env.call_count == 1


# ---------------------------------------------------------------- contract

def _make_backend_with_mock_client() -> tuple[KaliBackend, MagicMock]:
    with patch("app.agents.backends.kali.docker.DockerClient") as dc:
        client = MagicMock(name="docker-client")
        # containers.create returns a container with .id + a (no-op) .start()
        created = MagicMock(id="container-abc123")
        client.containers.create.return_value = created
        dc.return_value = client
        kb = KaliBackend()
    return kb, client


@pytest.mark.asyncio
async def test_start_passes_full_hardening_contract() -> None:
    kb, client = _make_backend_with_mock_client()
    exec_id = await kb.start(
        image="osa-kali:latest",
        command=["gobuster", "dir", "--url", "http://target/"],
        env={"FOO": "bar"},
        network=None,
        resource_limits={"mem_limit": "256m", "cpu_quota": 50000, "pids_limit": 80},
    )
    assert exec_id == "container-abc123"
    client.containers.create.assert_called_once()
    kwargs = client.containers.create.call_args.kwargs
    assert kwargs["security_opt"] == KALI_SECURITY_OPT
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["cap_add"] == []  # v1: KALI_ALLOWED_CAPS=frozenset()
    assert kwargs["read_only"] is True
    assert kwargs["tmpfs"] == KALI_TMPFS
    assert kwargs["network_disabled"] is True  # network=None ⇒ True
    assert kwargs["mem_limit"] == "256m"
    assert kwargs["cpu_quota"] == 50000
    assert kwargs["pids_limit"] == 80
    # create + explicit start (not containers.run) — see the start-failure cleanup test.
    client.containers.create.return_value.start.assert_called_once()


@pytest.mark.asyncio
async def test_start_uses_default_limits_when_unset() -> None:
    kb, client = _make_backend_with_mock_client()
    await kb.start(
        image="osa-kali:latest",
        command=["nikto", "-h", "http://target/"],
        env={},
        network=None,
        resource_limits={},
    )
    kwargs = client.containers.create.call_args.kwargs
    assert kwargs["mem_limit"] == "512m"
    assert kwargs["cpu_quota"] == 100000
    assert kwargs["pids_limit"] == 100


@pytest.mark.asyncio
async def test_start_respects_explicit_network() -> None:
    kb, client = _make_backend_with_mock_client()
    await kb.start(
        image="osa-kali:latest",
        command=["sqlmap", "-u", "http://target/?id=1", "--batch"],
        env={},
        network="osa_pentest_net",
        resource_limits={},
    )
    kwargs = client.containers.create.call_args.kwargs
    assert kwargs["network"] == "osa_pentest_net"
    assert kwargs["network_disabled"] is False  # network set ⇒ disabled=False


# ---------------------------------------------------------------- cap_add

@pytest.mark.asyncio
async def test_start_rejects_cap_add_outside_kali_allowed_caps() -> None:
    kb, client = _make_backend_with_mock_client()
    with pytest.raises(SafetyViolation) as excinfo:
        await kb.start(
            image="osa-kali:latest",
            command=["gobuster", "dir", "--url", "http://x/"],
            env={},
            network=None,
            resource_limits={"cap_add": ["NET_RAW"]},
        )
    assert "NET_RAW" in str(excinfo.value)
    assert "KALI_ALLOWED_CAPS" in str(excinfo.value)
    client.containers.create.assert_not_called()


@pytest.mark.asyncio
async def test_start_allows_empty_cap_add() -> None:
    kb, client = _make_backend_with_mock_client()
    exec_id = await kb.start(
        image="osa-kali:latest",
        command=["nikto", "-h", "http://x/"],
        env={},
        network=None,
        resource_limits={"cap_add": []},
    )
    assert exec_id == "container-abc123"
    kwargs = client.containers.create.call_args.kwargs
    assert kwargs["cap_add"] == []


# ---------------------------------------------------------------- cleanup

@pytest.mark.asyncio
async def test_cleanup_force_removes_container() -> None:
    kb, client = _make_backend_with_mock_client()
    container = MagicMock(name="container")
    client.containers.get.return_value = container
    await kb.cleanup("container-abc123")
    container.remove.assert_called_once_with(force=True)


@pytest.mark.asyncio
async def test_cleanup_swallows_not_found() -> None:
    from docker.errors import NotFound as _NotFound

    kb, client = _make_backend_with_mock_client()
    client.containers.get.side_effect = _NotFound("gone")
    # Should not raise.
    await kb.cleanup("container-abc123")


@pytest.mark.asyncio
async def test_stop_calls_container_stop_with_timeout() -> None:
    kb, client = _make_backend_with_mock_client()
    container = MagicMock(name="container")
    client.containers.get.return_value = container
    await kb.stop("container-abc123")
    container.stop.assert_called_once_with(timeout=5)


# ------------------------------------------------ start-failure cleanup (no zombie)


@pytest.mark.asyncio
async def test_start_failure_removes_created_container_no_zombie() -> None:
    """A START failure (e.g. the misconfigured `seccomp=default` OCI error that
    left osa-kali 'created' zombies) must force-remove the CREATED container and
    re-raise — not leak a lingering 'created'-state container."""
    from docker.errors import APIError

    kb, client = _make_backend_with_mock_client()
    created = client.containers.create.return_value
    created.start.side_effect = APIError("Decoding seccomp profile failed")

    with pytest.raises(APIError):
        await kb.start(
            image="osa-kali:latest", command=["nikto", "-h", "http://x/"],
            env={}, network=None, resource_limits={},
        )
    created.remove.assert_called_once_with(force=True)


@pytest.mark.asyncio
async def test_start_failure_swallows_cleanup_error_but_reraises_original() -> None:
    """If the cleanup remove() itself fails, the ORIGINAL start error still
    propagates (the cleanup must never mask the real failure)."""
    from docker.errors import APIError

    kb, client = _make_backend_with_mock_client()
    created = client.containers.create.return_value
    created.start.side_effect = APIError("oci start boom")
    created.remove.side_effect = RuntimeError("remove also broke")

    with pytest.raises(APIError, match="oci start boom"):
        await kb.start(
            image="osa-kali:latest", command=["nikto"],
            env={}, network=None, resource_limits={},
        )


@pytest.mark.asyncio
async def test_docker_backend_start_failure_removes_created_container() -> None:
    """DockerBackend (legacy path) also force-removes a container whose start fails."""
    from docker.errors import APIError

    with patch("docker.from_env") as from_env:
        client = MagicMock(name="docker-client")
        created = MagicMock(id="c1")
        created.start.side_effect = APIError("start boom")
        client.containers.create.return_value = created
        from_env.return_value = client
        db = DockerBackend()

    with pytest.raises(APIError):
        await db.start(
            image="osa-agent-nmap:latest", command=["-sV"],
            env={}, network="bridge", resource_limits={},
        )
    created.remove.assert_called_once_with(force=True)
