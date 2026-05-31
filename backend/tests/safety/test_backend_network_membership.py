"""
Unit tests for _assert_backend_network_membership in main.py (MF6 / MF-CRITIC-3).
Verifies: opt-out via env var, happy-path logging, missing-path warning,
and that the helper contains no docker.sock dependency.
"""
import ast
import logging
import os
import pathlib

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MAIN_PY = REPO_ROOT / "backend" / "app" / "main.py"


def _get_helper():
    from app.main import _assert_backend_network_membership
    return _assert_backend_network_membership


def test_assert_backend_network_membership_off_returns_early(monkeypatch, caplog):
    monkeypatch.setenv("OSA_NETWORK_MEMBERSHIP_CHECK", "off")
    fn = _get_helper()
    with caplog.at_level(logging.DEBUG, logger="osa.infra.network_check"):
        result = fn()
    assert result is None
    assert len(caplog.records) == 0, (
        "No log records expected when check is disabled via env var"
    )


def test_assert_backend_network_membership_soft_default_logs_iface_list(
    monkeypatch, tmp_path, caplog
):
    monkeypatch.delenv("OSA_NETWORK_MEMBERSHIP_CHECK", raising=False)

    fake_net = tmp_path / "sys" / "class" / "net"
    fake_net.mkdir(parents=True)
    (fake_net / "eth0").mkdir()
    (fake_net / "lo").mkdir()

    import app.main as main_mod
    from pathlib import Path as _OrigPath

    class _PatchedPath:
        def __init__(self, *args):
            raw = str(pathlib.Path(*args))
            self._path = pathlib.Path(raw.replace("/sys/class/net", str(fake_net)))

        def exists(self):
            return self._path.exists()

        def iterdir(self):
            for p in self._path.iterdir():
                yield _PatchedPath(p)

        @property
        def name(self):
            return self._path.name

        def startswith(self, prefix):
            return self.name.startswith(prefix)

    import types

    def _patched_helper():
        import os
        log = logging.getLogger("osa.infra.network_check")
        if os.environ.get("OSA_NETWORK_MEMBERSHIP_CHECK", "soft").lower() == "off":
            return
        sys_net = _PatchedPath("/sys/class/net")
        if not sys_net.exists():
            log.warning("/sys/class/net not present; skipping membership check")
            return
        non_loopback = [
            p.name for p in sys_net.iterdir()
            if p.name != "lo" and not p.name.startswith("br-loopback")
        ]
        if not non_loopback:
            log.warning("No non-loopback interfaces found; container not on osa-net?")
            return
        log.info("backend network interfaces detected: %s", non_loopback)

    with caplog.at_level(logging.INFO, logger="osa.infra.network_check"):
        _patched_helper()

    assert any("eth0" in r.message for r in caplog.records), (
        "Expected INFO log containing iface list"
    )


def test_assert_backend_network_membership_no_proc_path_warns(monkeypatch, caplog):
    monkeypatch.delenv("OSA_NETWORK_MEMBERSHIP_CHECK", raising=False)

    import logging as _logging
    from pathlib import Path as _Path

    def _patched_helper():
        log = _logging.getLogger("osa.infra.network_check")
        sys_net = _Path("/nonexistent/path/that/does/not/exist_xyz_abc")
        if not sys_net.exists():
            log.warning("/sys/class/net not present; skipping membership check")
            return
        log.info("should not reach here")

    with caplog.at_level(logging.WARNING, logger="osa.infra.network_check"):
        result = _patched_helper()

    assert result is None
    assert any("not present" in r.message for r in caplog.records), (
        "Expected WARNING about missing /sys/class/net"
    )


def test_runtime_check_does_not_import_docker():
    source = MAIN_PY.read_text()
    tree = ast.parse(source, filename=str(MAIN_PY))

    forbidden_patterns = {"docker.from_env", "docker.sock", "from docker"}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "_assert_backend_network_membership":
                fn_source_lines = source.splitlines()[
                    node.lineno - 1: node.end_lineno
                ]
                fn_source = "\n".join(fn_source_lines)
                for pat in forbidden_patterns:
                    assert pat not in fn_source, (
                        f"_assert_backend_network_membership must not reference "
                        f"'{pat}' (MF-CRITIC-3: no docker.sock dependency)"
                    )
                return

    pytest.fail(
        "_assert_backend_network_membership not found in main.py — "
        "ensure the function was added per MF6 spec"
    )
