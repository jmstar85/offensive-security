"""KaliBackend.start() hardening contract — mock-based verification.

Per the consensus plan (ralplan-kali-coexistence-v1.md §A1.2), every
KaliBackend.start() call MUST pass the following kwargs to docker-py
`containers.run()`:

  - security_opt = ["no-new-privileges:true", "seccomp=default"]
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
    # Both backends call `docker.from_env()`; patching the symbol once and
    # using `side_effect` to yield distinct objects exercises the property
    # we actually care about: each backend __init__ calls from_env() and
    # captures its own client (no shared singleton).
    with patch("docker.from_env") as from_env:
        from_env.side_effect = [
            MagicMock(name="kali-client"),
            MagicMock(name="docker-client"),
        ]
        kb = KaliBackend()
        db = DockerBackend()
    assert kb._client is not db._client
    assert from_env.call_count == 2


# ---------------------------------------------------------------- contract

def _make_backend_with_mock_client() -> tuple[KaliBackend, MagicMock]:
    with patch("app.agents.backends.kali.docker.from_env") as from_env:
        client = MagicMock(name="docker-client")
        # containers.run returns an object with .id
        run_result = MagicMock(id="container-abc123")
        client.containers.run.return_value = run_result
        from_env.return_value = client
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
    client.containers.run.assert_called_once()
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["security_opt"] == KALI_SECURITY_OPT
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["cap_add"] == []  # v1: KALI_ALLOWED_CAPS=frozenset()
    assert kwargs["read_only"] is True
    assert kwargs["tmpfs"] == KALI_TMPFS
    assert kwargs["network_disabled"] is True  # network=None ⇒ True
    assert kwargs["mem_limit"] == "256m"
    assert kwargs["cpu_quota"] == 50000
    assert kwargs["pids_limit"] == 80
    assert kwargs["detach"] is True
    assert kwargs["remove"] is False


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
    kwargs = client.containers.run.call_args.kwargs
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
    kwargs = client.containers.run.call_args.kwargs
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
    client.containers.run.assert_not_called()


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
    kwargs = client.containers.run.call_args.kwargs
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
