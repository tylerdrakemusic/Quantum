from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from quantum_toolkit.execution_planner import (
    AvailabilitySnapshot,
    NormalizedRequest,
    PlannerContractError,
    PlannerStatus,
    plan_execution,
)
from quantum_toolkit.provider_fixtures import fixture_snapshots


NOW = "2026-09-19T12:00:00Z"


def request(*, requires_hardware: bool = False) -> NormalizedRequest:
    return NormalizedRequest.from_dict(
        {
            "schema_version": "1.0",
            "request_id": "planner-test",
            "qubits": 4,
            "depth": 8,
            "shots": 100,
            "estimated_duration_seconds": 5,
            "requires_hardware": requires_hardware,
            "allow_simulator_fallback": True,
            "hardware_approval_required": False,
        }
    )


def snapshot(**overrides: object) -> AvailabilitySnapshot:
    values = {
        "provider_id": "local-aer",
        "provider": "local",
        "execution_mode": "simulator",
        "available": True,
        "observed_at": "2026-09-19T11:59:00Z",
        "freshness_seconds": 3600,
        "max_qubits": 32,
        "quota_remaining_seconds": 0,
    }
    values.update(overrides)
    return AvailabilitySnapshot.from_dict(values)


def test_request_requires_explicit_versioned_workload_fields() -> None:
    with pytest.raises(PlannerContractError, match="schema_version"):
        NormalizedRequest.from_dict({"qubits": 2, "depth": 3, "shots": 100})


def test_fresh_simulator_is_runnable() -> None:
    result = plan_execution(request(), [snapshot()], now_utc=NOW)

    assert result.status is PlannerStatus.RUNNABLE_SIMULATOR
    assert result.selected_provider_id == "local-aer"


def test_stale_hardware_uses_optional_simulator_fallback() -> None:
    result = plan_execution(
        request(),
        [
            snapshot(
                provider_id="ibm-fez",
                provider="ibm",
                execution_mode="hardware",
                observed_at="2026-09-19T10:00:00Z",
                freshness_seconds=60,
                max_qubits=156,
                quota_remaining_seconds=60,
            ),
            snapshot(),
        ],
        now_utc=NOW,
    )

    assert result.status is PlannerStatus.FALLBACK_RECOMMENDED
    assert result.selected_provider_id == "local-aer"
    assert "stale_hardware_snapshot" in result.reason_codes


def test_hardware_approval_is_required_before_a_hardware_plan() -> None:
    result = plan_execution(
        request(),
        [
            snapshot(
                provider_id="ibm-fez",
                provider="ibm",
                execution_mode="hardware",
                observed_at="2026-09-19T11:59:00Z",
                freshness_seconds=3600,
                quota_remaining_seconds=60,
            )
        ],
        now_utc=NOW,
    )
    approved_request = NormalizedRequest.from_dict(
        {**request().to_dict(), "hardware_approval_required": True}
    )

    approval = plan_execution(approved_request, [snapshot(
        provider_id="ibm-fez",
        provider="ibm",
        execution_mode="hardware",
        observed_at="2026-09-19T11:59:00Z",
        freshness_seconds=3600,
        quota_remaining_seconds=60,
    )], now_utc=NOW)

    assert result.status is PlannerStatus.RUNNABLE_HARDWARE_PLAN
    assert approval.status is PlannerStatus.APPROVAL_REQUIRED


def test_hardware_required_with_stale_snapshot_is_blocked() -> None:
    result = plan_execution(
        request(requires_hardware=True),
        [snapshot(
            provider_id="ibm-fez",
            provider="ibm",
            execution_mode="hardware",
            observed_at="2026-09-19T10:00:00Z",
            freshness_seconds=60,
            max_qubits=156,
            quota_remaining_seconds=60,
        )],
        now_utc=NOW,
    )

    assert result.status is PlannerStatus.BLOCKED
    assert result.selected_provider_id is None


def test_provider_order_does_not_change_serialized_plan() -> None:
    snapshots = [
        snapshot(provider_id="local-z", provider="local"),
        snapshot(provider_id="local-a", provider="local"),
    ]

    first = plan_execution(request(), snapshots, now_utc=NOW).to_dict()
    second = plan_execution(request(), list(reversed(snapshots)), now_utc=NOW).to_dict()

    assert first == second


def test_static_provider_fixtures_are_credential_free() -> None:
    fixtures = fixture_snapshots()

    assert {item.provider for item in fixtures} == {"ibm", "braket", "local"}
    assert all(item.observed_at.tzinfo is not None for item in fixtures)


def test_dry_run_cli_emits_deterministic_json() -> None:
    request_json = json.dumps(request().to_dict())
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    command = [
        sys.executable,
        "tools/plan_execution.py",
        "--request-json",
        request_json,
        "--fixture",
        "local",
        "--now-utc",
        NOW,
    ]

    first = subprocess.run(command, check=True, capture_output=True, text=True, env=environment)
    second = subprocess.run(command, check=True, capture_output=True, text=True, env=environment)

    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["result"]["status"] == "runnable_simulator"


def test_dry_run_cli_can_write_matching_provenance(tmp_path: Path) -> None:
    request_json = json.dumps(request().to_dict())
    provenance = tmp_path / "planner-provenance.json"
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(
        [
            sys.executable,
            "tools/plan_execution.py",
            "--request-json",
            request_json,
            "--fixture",
            "local",
            "--now-utc",
            NOW,
            "--provenance",
            str(provenance),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    artifact = provenance.read_text(encoding="utf-8")
    assert result.stdout == artifact
    assert json.loads(artifact)["planner_schema_version"] == "1.0"