"""Shim tests — verify load harness imports cleanly without a real locust runtime."""
from __future__ import annotations
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


def _stub_locust(monkeypatch: "pytest.MonkeyPatch") -> None:
    """Inject a minimal locust stub so the harness module can be imported."""
    locust_stub = types.ModuleType("locust")

    def between(min_wait: float, max_wait: float):
        return lambda self: min_wait

    def task(weight=1):
        def decorator(fn):
            fn.locust_task_weight = weight
            return fn
        return decorator

    class HttpUser:
        abstract = True

    locust_stub.HttpUser = HttpUser
    locust_stub.task = task
    locust_stub.between = between
    locust_stub.events = MagicMock()

    monkeypatch.setitem(sys.modules, "locust", locust_stub)
    # Remove any cached version of the harness module so we get a fresh import
    monkeypatch.delitem(sys.modules, "tests._load.multi_user_load_harness", raising=False)


def test_load_harness_module_importable_without_locust_runtime(monkeypatch):
    _stub_locust(monkeypatch)
    mod = importlib.import_module("tests._load.multi_user_load_harness")
    assert mod.LOAD_HARNESS_VERSION.startswith("1.0")


def test_load_harness_uses_api_prefix_env_var(monkeypatch):
    _stub_locust(monkeypatch)
    monkeypatch.setenv("OSA_API_PREFIX", "/api/v1")
    mod = importlib.import_module("tests._load.multi_user_load_harness")
    # The module reads from os.environ at import time; verify the attribute exists with the default
    assert hasattr(mod, "API_PREFIX")
    assert mod.API_PREFIX == "/api/v1"


def test_load_harness_class_defines_required_tasks(monkeypatch):
    _stub_locust(monkeypatch)
    mod = importlib.import_module("tests._load.multi_user_load_harness")
    user_cls = mod.OsaMultiUser
    assert hasattr(user_cls, "start_pentest_session"), "OsaMultiUser must define start_pentest_session"
    assert hasattr(user_cls, "list_audit_logs"), "OsaMultiUser must define list_audit_logs"


def test_load_harness_does_not_contain_hardcoded_credentials():
    harness_path = Path(__file__).parent.parent / "_load" / "multi_user_load_harness.py"
    source = harness_path.read_text()
    # Forbidden secret patterns
    for bad_pattern in ("sk-", "AKIA", "ghp_", "Bearer ey"):
        assert bad_pattern not in source, f"Harness source must not contain '{bad_pattern}'"
    # Sanity check: known test fixture password IS present so the assertions above are meaningful
    assert "loadtest-pw" in source, "Expected test fixture password 'loadtest-pw' to be present"
