"""
Tests for the quarterly sidecar digest refresh workflow (PR5.2).
Parses the workflow YAML and asserts contract invariants.
"""
import re
import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
WORKFLOW_FILE = REPO_ROOT / ".github" / "workflows" / "sidecar-digest-refresh-quarterly.yml"


@pytest.fixture(scope="module")
def workflow():
    with open(WORKFLOW_FILE) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def workflow_text():
    return WORKFLOW_FILE.read_text()


def _on(workflow):
    """PyYAML parses YAML 1.1 'on:' as boolean True. Tolerate both."""
    return workflow.get("on") or workflow.get(True) or {}


@pytest.fixture(scope="module")
def matrix_sidecars(workflow):
    return workflow["jobs"]["refresh"]["strategy"]["matrix"]["sidecar"]


def test_workflow_runs_quarterly(workflow):
    schedules = _on(workflow)["schedule"]
    crons = [s["cron"] for s in schedules]
    assert "0 4 1 1,4,7,10 *" in crons, (
        f"Expected quarterly cron '0 4 1 1,4,7,10 *', got: {crons}"
    )


def test_workflow_matrix_covers_three_sidecars(matrix_sidecars):
    names = {s["name"] for s in matrix_sidecars}
    assert "mitmproxy" in names, "matrix must include mitmproxy"
    assert "headless-browser" in names, "matrix must include headless-browser"
    assert "interactsh" in names, "matrix must include interactsh"
    assert len(names) == 3, f"Expected exactly 3 sidecars, got: {names}"


def test_workflow_uses_OSA_DIGEST_env_names(matrix_sidecars):
    pattern = re.compile(r"^OSA_[A-Z_]+_DIGEST$")
    for sidecar in matrix_sidecars:
        env_name = sidecar["env"]
        assert pattern.match(env_name), (
            f"Sidecar {sidecar['name']} env '{env_name}' does not match OSA_*_DIGEST pattern"
        )


def test_workflow_verifies_digest_sha256_format(workflow_text):
    assert r"^sha256:[a-f0-9]{64}$" in workflow_text, (
        "Workflow must contain sha256 digest format verification regex"
    )


def test_workflow_opens_pull_request_not_force_push(workflow_text):
    assert "peter-evans/create-pull-request" in workflow_text, (
        "Workflow must use peter-evans/create-pull-request action, not force-push"
    )


def test_workflow_has_manual_dispatch(workflow):
    triggers = _on(workflow)
    assert "workflow_dispatch" in triggers, (
        "Workflow must define workflow_dispatch for manual triggering"
    )


def test_workflow_does_not_skip_review(workflow_text):
    assert "auto-merge" not in workflow_text, (
        "Workflow must NOT contain auto-merge step — human review required"
    )
