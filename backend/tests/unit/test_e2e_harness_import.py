"""Shim tests — confirm e2e module imports cleanly without live targets."""
import importlib
import inspect
import os
import sys


def test_e2e_module_importable_without_targets():
    for var in ("OSA_E2E_DVWA_URL", "OSA_E2E_JUICE_URL"):
        os.environ.pop(var, None)
    import tests.e2e.conftest as e2e_conftest
    assert callable(e2e_conftest.pytest_collection_modifyitems)


def test_e2e_test_class_count():
    import tests.e2e.test_attack_vector_e2e as m
    classes = [
        name for name, obj in inspect.getmembers(m, inspect.isclass)
        if name.startswith("Test")
    ]
    assert len(classes) == 6, f"Expected 6 test classes, found {len(classes)}: {classes}"


def test_e2e_uses_env_overrides():
    import tests.e2e.test_attack_vector_e2e as m
    # Verify the module reads from os.environ (defaults are empty strings when unset)
    assert hasattr(m, "DVWA")
    assert hasattr(m, "JUICE")
    assert m.DVWA == os.environ.get("OSA_E2E_DVWA_URL", "")
    assert m.JUICE == os.environ.get("OSA_E2E_JUICE_URL", "")
