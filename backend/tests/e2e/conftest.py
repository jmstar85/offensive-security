"""Per-vector E2E gate — W4/PR4.5.

Tests in this folder require live DVWA + Juice Shop. They skip by
default in CI; opt-in via OSA_E2E_DVWA_URL + OSA_E2E_JUICE_URL env
vars. The shim_test in tests/unit/test_e2e_harness_import.py
confirms the module is at least importable without network.
"""
import os
import pytest

def pytest_collection_modifyitems(config, items):
    e2e_enabled = bool(os.environ.get("OSA_E2E_DVWA_URL")) and bool(os.environ.get("OSA_E2E_JUICE_URL"))
    if e2e_enabled:
        return
    skip = pytest.mark.skip(reason="E2E disabled — set OSA_E2E_DVWA_URL + OSA_E2E_JUICE_URL to enable")
    for item in items:
        if "e2e/" in str(item.fspath) or "tests/e2e/" in str(item.fspath):
            item.add_marker(skip)
