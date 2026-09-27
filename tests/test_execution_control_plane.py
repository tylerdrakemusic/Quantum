from __future__ import annotations

import sqlite3

import pytest

from quantum_toolkit.execution_control_plane import (
    AmazonBraketAdapter,
    ControlPlane,
    DecisionStatus,
    GateSnapshot,
    IBMQuantumAdapter,
    LifecycleState,
    SUPPORTED_FAMILIES,
)


def request_payload() -> dict[str, object]:
    return {
        "request_id": "run-1",
        "qubits": 4,
        "depth": 3,
        "shots": 20,
        "estimated_duration_seconds": 2,
        "requires_hardware": False,
        "allow_simulator_fallback": True,
        "hardware_approval_required": True,
    }


def all_gates(**overrides: bool) -> GateSnapshot:
    values = {
        "health": True,
        "quota": True,
        "credential_safe": True,
        "retry": True,
        "schedule": True,
        "policy": True,
        "approval": True,
    }
    values.update(overrides)
    return GateSnapshot(**values)


def test_all_benchmark_families_normalize_to_control_plane_requests() -> None:
    plane = ControlPlane()

    requests = [plane.normalize(family, request_payload()) for family in SUPPORTED_FAMILIES]

    assert {request.family for request in requests} == set(SUPPORTED_FAMILIES)
    assert all(request.schema_version == "1.0" for request in requests)


def test_simulator_completes_and_persists_provenance_replay_evidence() -> None:
    conn = sqlite3.connect(":memory:")
    plane = ControlPlane()
    request = plane.normalize("qaoa", {**request_payload(), "parameters": {"api_key": "must-not-persist"}})

    result = plane.execute_simulator(
        request,
        execute=lambda seed: {"status": "pass", "objective": 0.9, "seed": seed},
        seed=7,
        conn=conn,
    )

    assert result.state is LifecycleState.COMPLETED
    assert result.decision.status is DecisionStatus.SUCCEEDED
    assert result.evidence_references
    assert conn.execute("SELECT COUNT(*) FROM execution_lifecycle").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM benchmark_provenance").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM benchmark_replays").fetchone()[0] == 1
    manifest = conn.execute("SELECT manifest_json FROM benchmark_provenance").fetchone()[0]
    assert "must-not-persist" not in manifest


def test_hardware_plan_requires_all_gates_and_explicit_approval() -> None:
    plane = ControlPlane()
    request = plane.normalize("shor", {**request_payload(), "requires_hardware": True})

    blocked = plane.plan_hardware(request, all_gates(health=False))
    approval = plane.plan_hardware(request, all_gates(approval=False))
    allowed = plane.plan_hardware(request, all_gates())

    assert blocked.status is DecisionStatus.BLOCKED
    assert approval.status is DecisionStatus.APPROVAL_REQUIRED
    assert allowed.status is DecisionStatus.PERMITTED


@pytest.mark.parametrize(
    "gate, status",
    [
        ("credential_safe", DecisionStatus.BLOCKED),
        ("quota", DecisionStatus.DEFERRED),
        ("retry", DecisionStatus.DEFERRED),
        ("schedule", DecisionStatus.DEFERRED),
        ("policy", DecisionStatus.BLOCKED),
    ],
)
def test_gate_failures_are_explicit(gate: str, status: DecisionStatus) -> None:
    plane = ControlPlane()
    request = plane.normalize("vqe", request_payload())

    result = plane.plan_hardware(request, all_gates(**{gate: False}))

    assert result.status is status
    assert gate in result.reason_codes


def test_provider_adapters_submit_only_after_guarded_permitted_decision() -> None:
    calls: list[dict[str, object]] = []
    request = ControlPlane().normalize("qec", request_payload())
    ibm = IBMQuantumAdapter(submit=lambda payload: calls.append(payload) or "ibm-job")
    braket = AmazonBraketAdapter(submit=lambda payload: calls.append(payload) or "braket-job")

    with pytest.raises(PermissionError):
        ibm.submit(request, ControlPlane().plan_hardware(request, all_gates(policy=False)))

    assert ibm.submit(request, ControlPlane().plan_hardware(request, all_gates())) == "ibm-job"
    assert braket.submit(request, ControlPlane().plan_hardware(request, all_gates())) == "braket-job"
    assert calls == [{"request_id": "run-1", "family": "qec"}] * 2