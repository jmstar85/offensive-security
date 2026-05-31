"""v1.1 byte-identical comparator utility — NOT a pytest test module."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

EXCLUDED_AUDIT_PREFIXES = (
    "coordinator.",
    "agent_family.",
    "mitm_exec.",
    "headless_exec.",
    "oob.",
    "conversation.",
    "raw_conversation.",
    "credential_",
    "infra.network_membership_violation",
    "admin.enrich_understanding",
    "llm.provider_call",
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)


def is_excluded_action(action: str) -> bool:
    return any(action.startswith(p) for p in EXCLUDED_AUDIT_PREFIXES)


def _normalise_uuid(val: str) -> str:
    if _UUID_RE.match(val):
        return str(uuid.UUID(val))
    return val


def _parse_iso(val: str) -> datetime | None:
    if not _ISO_RE.match(val):
        return None
    try:
        s = val.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _normalise_value(val: Any) -> Any:
    if isinstance(val, str):
        if _UUID_RE.match(val):
            return _normalise_uuid(val)
    return val


def _deep_compare(
    actual: Any,
    expected: Any,
    path: str,
    tolerance_ms: int,
    diffs: list[str],
) -> None:
    if isinstance(expected, dict) and isinstance(actual, dict):
        all_keys = set(expected) | set(actual)
        for k in sorted(all_keys):
            _deep_compare(
                actual.get(k), expected.get(k), f"{path}.{k}", tolerance_ms, diffs
            )
        return

    if isinstance(expected, list) and isinstance(actual, list):
        if len(actual) != len(expected):
            diffs.append(f"{path}: list length {len(actual)} != {len(expected)}")
            return
        for i, (a, e) in enumerate(zip(actual, expected)):
            _deep_compare(a, e, f"{path}[{i}]", tolerance_ms, diffs)
        return

    if isinstance(expected, str) and isinstance(actual, str):
        exp_dt = _parse_iso(expected)
        act_dt = _parse_iso(actual)
        if exp_dt is not None and act_dt is not None:
            diff_ms = abs((act_dt - exp_dt).total_seconds() * 1000)
            if diff_ms > tolerance_ms:
                diffs.append(
                    f"{path}: timestamp drift {diff_ms:.1f}ms > tolerance {tolerance_ms}ms"
                )
            return
        norm_actual = _normalise_value(actual)
        norm_expected = _normalise_value(expected)
        if norm_actual != norm_expected:
            diffs.append(f"{path}: {norm_actual!r} != {norm_expected!r}")
        return

    if actual != expected:
        diffs.append(f"{path}: {actual!r} != {expected!r}")


def _row_key(row: dict) -> tuple[str, str, str, str]:
    action = row.get("action", "")
    target_entity = row.get("target_entity", "")
    target_id = _normalise_uuid(str(row.get("target_id", "")))
    details = row.get("details_json", {})
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except (json.JSONDecodeError, TypeError):
            pass
    details_canonical = json.dumps(details, sort_keys=True)
    return (action, target_entity, target_id, details_canonical)


def compare_audit_log_rows(
    actual: list[dict],
    expected: list[dict],
    tolerance_ms: int = 50,
) -> list[str]:
    diffs: list[str] = []
    if len(actual) != len(expected):
        diffs.append(f"row count: {len(actual)} != {len(expected)}")
        return diffs
    for i, (a_row, e_row) in enumerate(zip(actual, expected)):
        prefix = f"row[{i}]"
        if a_row.get("action") != e_row.get("action"):
            diffs.append(f"{prefix}.action: {a_row.get('action')!r} != {e_row.get('action')!r}")
        if a_row.get("target_entity") != e_row.get("target_entity"):
            diffs.append(
                f"{prefix}.target_entity: {a_row.get('target_entity')!r} != {e_row.get('target_entity')!r}"
            )
        a_tid = _normalise_uuid(str(a_row.get("target_id", "")))
        e_tid = _normalise_uuid(str(e_row.get("target_id", "")))
        if a_tid != e_tid:
            diffs.append(f"{prefix}.target_id: {a_tid!r} != {e_tid!r}")
        # Top-level timestamp drift check (was missing; surfaced by W0/PR0.5
        # test_comparator_detects_timestamp_drift_within_tolerance). Compare
        # using the same ±tolerance_ms window applied inside details_json.
        a_ts = a_row.get("timestamp")
        e_ts = e_row.get("timestamp")
        if isinstance(a_ts, str) and isinstance(e_ts, str):
            a_dt = _parse_iso(a_ts)
            e_dt = _parse_iso(e_ts)
            if a_dt is not None and e_dt is not None:
                drift_ms = abs((a_dt - e_dt).total_seconds() * 1000)
                if drift_ms > tolerance_ms:
                    diffs.append(
                        f"{prefix}.timestamp: drift {drift_ms:.1f}ms > tolerance {tolerance_ms}ms"
                    )
            elif a_ts != e_ts:
                diffs.append(f"{prefix}.timestamp: {a_ts!r} != {e_ts!r}")
        a_details = a_row.get("details_json", {})
        e_details = e_row.get("details_json", {})
        if isinstance(a_details, str):
            try:
                a_details = json.loads(a_details)
            except (json.JSONDecodeError, TypeError):
                pass
        if isinstance(e_details, str):
            try:
                e_details = json.loads(e_details)
            except (json.JSONDecodeError, TypeError):
                pass
        _deep_compare(a_details, e_details, f"{prefix}.details_json", tolerance_ms, diffs)
    return diffs


def compare_agent_execution_rows(
    actual: list[dict],
    expected: list[dict],
    tolerance_ms: int = 50,
) -> list[str]:
    diffs: list[str] = []
    if len(actual) != len(expected):
        diffs.append(f"row count: {len(actual)} != {len(expected)}")
        return diffs
    for i, (a_row, e_row) in enumerate(zip(actual, expected)):
        prefix = f"exec_row[{i}]"
        if a_row.get("slug") != e_row.get("slug"):
            diffs.append(f"{prefix}.slug: {a_row.get('slug')!r} != {e_row.get('slug')!r}")
        a_args = a_row.get("normalised_args", {})
        e_args = e_row.get("normalised_args", {})
        _deep_compare(a_args, e_args, f"{prefix}.normalised_args", tolerance_ms, diffs)
        if a_row.get("exit_code") != e_row.get("exit_code"):
            diffs.append(
                f"{prefix}.exit_code: {a_row.get('exit_code')!r} != {e_row.get('exit_code')!r}"
            )
        a_findings = a_row.get("parsed_findings_canonical", [])
        e_findings = e_row.get("parsed_findings_canonical", [])
        _deep_compare(a_findings, e_findings, f"{prefix}.parsed_findings_canonical", tolerance_ms, diffs)
        a_started = a_row.get("started_at", "")
        e_started = e_row.get("started_at", "")
        if a_started and e_started:
            a_dt = _parse_iso(str(a_started))
            e_dt = _parse_iso(str(e_started))
            if a_dt and e_dt:
                diff_ms = abs((a_dt - e_dt).total_seconds() * 1000)
                if diff_ms > tolerance_ms:
                    diffs.append(
                        f"{prefix}.started_at: drift {diff_ms:.1f}ms > tolerance {tolerance_ms}ms"
                    )
    return diffs


def assert_no_coordinator_in_saved_workflow_trace(trace: list[dict]) -> None:
    violations = [
        row for row in trace if str(row.get("action", "")).startswith("coordinator.")
    ]
    if violations:
        actions = [r["action"] for r in violations]
        raise AssertionError(
            f"saved-workflow trace must not contain coordinator.* events; found: {actions}"
        )
