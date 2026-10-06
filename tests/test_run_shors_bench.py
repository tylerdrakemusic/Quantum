"""Tests for tools/run_shors_bench.py."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "tools"))
sys.path.insert(0, str(_PROJECT_ROOT / "src" / "utils"))

import init_db  # noqa: E402
import run_shors_bench as rsb  # noqa: E402
from quantum_toolkit.execution_planner import AvailabilitySnapshot  # noqa: E402


@pytest.fixture
def quantum_db_env(tmp_path, monkeypatch):
    """Real sqlite job_retry_status DB so RetrySupervisor wiring can persist status."""
    db_path = tmp_path / "quantumpsi.db"
    monkeypatch.setenv("QUANTUM_DB_PATH", str(db_path))
    monkeypatch.setenv("QUANTUM_DB_KEY", "testkey")
    monkeypatch.setattr(init_db, "DB_PATH", db_path)
    init_db.init_db()
    yield db_path


class _FakeQiskitSamplerResult:
    def __init__(self, counts: dict[str, int], execution_seconds: float = 1.23) -> None:
        self.metadata = {"execution": {"execution_spans_seconds": execution_seconds}}
        self._counts = counts

    def get_counts(self) -> dict[str, int]:
        return self._counts

    def __getitem__(self, item):
        raise TypeError("'Result' object is not subscriptable")


def _fake_circuit(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    fake_qc = MagicMock()
    fake_qc.depth.return_value = 12
    fake_qc.count_ops.return_value = {"cx": 10}
    monkeypatch.setattr(rsb, "_build_shor_circuit_n15", lambda n_count: (fake_qc, 8))
    return fake_qc


def _hardware_snapshot(*, observed_at: str = "2026-09-01T08:00:00Z") -> AvailabilitySnapshot:
    return AvailabilitySnapshot.from_dict({
        "provider_id": "ibm-quantum",
        "provider": "ibm",
        "execution_mode": "hardware",
        "available": True,
        "observed_at": observed_at,
        "freshness_seconds": 3600,
        "max_qubits": 156,
        "quota_remaining_seconds": 300,
    })


def _simulator_snapshot() -> AvailabilitySnapshot:
    return AvailabilitySnapshot.from_dict({
        "provider_id": "local-aer",
        "provider": "local",
        "execution_mode": "simulator",
        "available": True,
        "observed_at": "2026-09-01T07:59:59Z",
        "freshness_seconds": 3600,
        "max_qubits": 32,
        "quota_remaining_seconds": 0,
    })


def test_planner_blocks_before_credentials_when_hardware_snapshot_is_missing(
    monkeypatch: pytest.MonkeyPatch, quantum_db_env,
) -> None:
    _fake_circuit(monkeypatch)
    monkeypatch.setattr(rsb, "_load_backend_snapshots", lambda *args: ())
    monkeypatch.setattr(
        rsb, "_get_ibm_credentials", lambda: pytest.fail("credentials must not be read"),
    )

    result = rsb.run_benchmark(
        dry_run=False,
        approved=True,
        now_utc="2026-09-01T08:00:00Z",
    )

    assert result["planner_status"] == "blocked"
    assert "no_provider_fit" in result["planner_result"]["reason_codes"]


def test_backend_snapshots_include_local_aer_when_package_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    connection.execute.return_value.fetchall.return_value = []
    aer_module = MagicMock(AerSimulator=MagicMock())
    monkeypatch.setitem(sys.modules, "qiskit_aer", aer_module)

    snapshots = rsb._load_backend_snapshots(
        connection,
        datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc),
        300,
    )

    assert [snapshot.provider_id for snapshot in snapshots] == ["local-aer"]
    assert snapshots[0].available is True


def test_planner_requires_explicit_approval_for_hardware(
    monkeypatch: pytest.MonkeyPatch, quantum_db_env,
) -> None:
    _fake_circuit(monkeypatch)
    monkeypatch.setattr(rsb, "_load_backend_snapshots", lambda *args: (_hardware_snapshot(),))
    monkeypatch.setattr(
        rsb, "_get_ibm_credentials", lambda: pytest.fail("approval must precede credentials"),
    )

    result = rsb.run_benchmark(
        dry_run=False,
        approved=False,
        now_utc="2026-09-01T08:00:00Z",
    )

    assert result["planner_status"] == "approval_required"
    assert result["planner_result"]["selected_provider_id"] == "ibm-quantum"


def test_stale_hardware_runs_eligible_simulator_fallback(
    monkeypatch: pytest.MonkeyPatch, quantum_db_env,
) -> None:
    circuit = _fake_circuit(monkeypatch)
    monkeypatch.setattr(
        rsb, "_load_backend_snapshots",
        lambda *args: (_hardware_snapshot(observed_at="2026-08-01T08:00:00Z"), _simulator_snapshot()),
    )
    monkeypatch.setattr(
        rsb, "_get_ibm_credentials", lambda: pytest.fail("Aer fallback must not read IBM credentials"),
    )

    fake_simulator = MagicMock()
    fake_simulator.run.return_value.result.return_value.get_counts.return_value = {
        "1111": rsb.N_SHOTS,
    }
    monkeypatch.setitem(
        sys.modules,
        "qiskit_aer",
        MagicMock(AerSimulator=MagicMock(return_value=fake_simulator)),
    )
    monkeypatch.setitem(sys.modules, "qiskit", MagicMock(transpile=MagicMock(return_value=circuit)))

    result = rsb.run_benchmark(
        dry_run=False,
        approved=True,
        now_utc="2026-09-01T08:00:00Z",
    )

    assert result["planner_status"] == "runnable_simulator"
    assert result["backend"] == "local-aer"
    fake_simulator.run.assert_called_once_with(circuit, shots=rsb.N_SHOTS)


def test_shors_runs_aer_for_eligible_fallback_without_reading_hardware_credentials(
    monkeypatch: pytest.MonkeyPatch, quantum_db_env,
) -> None:
    circuit = _fake_circuit(monkeypatch)
    monkeypatch.setattr(rsb, "_load_backend_snapshots", lambda *args: (_simulator_snapshot(),))
    monkeypatch.setattr(
        rsb, "_get_ibm_credentials", lambda: pytest.fail("Aer fallback must not read IBM credentials"),
    )

    fake_simulator = MagicMock()
    fake_simulator.run.return_value.result.return_value.get_counts.return_value = {
        "1111": rsb.N_SHOTS,
    }
    aer_module = MagicMock(AerSimulator=MagicMock(return_value=fake_simulator))
    qiskit_module = MagicMock(transpile=MagicMock(return_value=circuit))
    monkeypatch.setitem(sys.modules, "qiskit_aer", aer_module)
    monkeypatch.setitem(sys.modules, "qiskit", qiskit_module)

    result = rsb.run_benchmark(
        dry_run=False,
        approved=False,
        now_utc="2026-09-01T08:00:00Z",
    )

    assert result["planner_status"] == "runnable_simulator"
    assert result["backend"] == "local-aer"
    assert result["qpu_seconds"] == 0.0
    fake_simulator.run.assert_called_once_with(circuit, shots=rsb.N_SHOTS)


def test_outside_monthly_window_defers_before_credentials(
    monkeypatch: pytest.MonkeyPatch, quantum_db_env,
) -> None:
    _fake_circuit(monkeypatch)
    monkeypatch.setattr(rsb, "_load_backend_snapshots", lambda *args: pytest.fail("health must not be read"))
    monkeypatch.setattr(
        rsb, "_get_ibm_credentials", lambda: pytest.fail("outside window must defer"),
    )

    result = rsb.run_benchmark(
        dry_run=False,
        approved=True,
        now_utc="2026-09-01T09:00:01Z",
    )

    assert result["planner_status"] == "deferred"
    assert result["deferred"] is True
    assert "outside_schedule_window" in result["planner_result"]["reason_codes"]


def test_load_backend_snapshots_reads_latest_persisted_health_rows(
    quantum_db_env, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "qiskit_aer", MagicMock(AerSimulator=MagicMock()))
    conn = init_db.get_connection()
    conn.execute(
        "INSERT INTO backend_health (provider, status, checked_at) VALUES (?, ?, ?)",
        ("ibm_quantum", "up", "2026-09-01T07:59:00Z"),
    )
    conn.execute(
        "INSERT INTO backend_health (provider, status, checked_at) VALUES (?, ?, ?)",
        ("amazon_braket", "up", "2026-09-01T07:59:00Z"),
    )
    conn.commit()

    snapshots = rsb._load_backend_snapshots(
        conn, datetime(2026, 9, 1, 8, tzinfo=timezone.utc), rsb.MAX_QPU_SECONDS,
    )
    conn.close()

    assert [snapshot.provider_id for snapshot in snapshots] == [
        "amazon-braket", "ibm-quantum", "local-aer",
    ]
    assert snapshots[1].execution_mode == "hardware"
    assert snapshots[1].available is True


@pytest.mark.parametrize(
    ("planner_status", "expected_exit"),
    [("deferred", 0), ("fallback_recommended", 0), ("blocked", 1), ("approval_required", 2)],
)
def test_main_records_planner_payload_and_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    planner_status: str,
    expected_exit: int,
) -> None:
    args = argparse.Namespace(
        n=15,
        max_qpu_seconds=rsb.MAX_QPU_SECONDS,
        dry_run=False,
        defer_reason="",
        manual_override_note="",
        approved=False,
        now_utc="2026-09-01T08:00:00Z",
    )
    result = {
        "planner_status": planner_status,
        "planner_request": {"request_id": "request-1"},
        "planner_result": {"status": planner_status, "reason_codes": ["test"]},
    }
    events: list[dict[str, str]] = []
    monkeypatch.setattr(rsb, "_parse_args", lambda: args)
    monkeypatch.setattr(rsb, "run_benchmark", lambda **kwargs: result)
    monkeypatch.setattr(
        rsb, "log_policy_event", lambda **kwargs: events.append(kwargs),
    )

    with pytest.raises(SystemExit) as exc_info:
        rsb.main()

    assert exc_info.value.code == expected_exit
    planner_event = events[-1]
    assert planner_event["status"] in {"deferred", "blocked", "approval_required"}
    assert '"planner_request"' in planner_event["detail"]
    assert '"planner_result"' in planner_event["detail"]


def test_main_correlates_started_and_terminal_events_with_attempt_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = argparse.Namespace(
        n=15,
        max_qpu_seconds=rsb.MAX_QPU_SECONDS,
        dry_run=True,
        defer_reason="",
        manual_override_note="",
        approved=False,
        now_utc="2026-09-01T08:00:00Z",
    )
    events: list[dict[str, str]] = []
    monkeypatch.setattr(rsb, "_parse_args", lambda: args)
    monkeypatch.setattr(rsb, "run_benchmark", lambda **kwargs: {"planner_status": "runnable_hardware_plan"})
    monkeypatch.setattr(rsb, "log_policy_event", lambda **kwargs: events.append(kwargs))

    with pytest.raises(SystemExit) as exc_info:
        rsb.main()

    assert exc_info.value.code == 0
    started = next(event for event in events if event["event_type"] == "run_started")
    terminal = next(event for event in events if event["event_type"] == "run_completed")
    assert started["attempt_id"]
    assert started["attempt_id"] == terminal["attempt_id"]


def test_run_shors_bench_uses_result_get_counts(monkeypatch: pytest.MonkeyPatch, quantum_db_env) -> None:
    """The benchmark should use result.get_counts() when supported."""
    fake_counts = {"0010": 4096}
    fake_qc = MagicMock()
    fake_qc.depth.return_value = 4
    fake_qc.count_ops.return_value = {"cx": 10}

    monkeypatch.setattr(rsb, "_build_shor_circuit_n15", lambda n_count: (fake_qc, 8))
    monkeypatch.setattr(rsb, "_load_backend_snapshots", lambda *args: (_hardware_snapshot(),))
    monkeypatch.setattr(rsb, "_get_ibm_credentials", lambda: ("key", "instance"))

    fake_backend = MagicMock()
    fake_backend.name = "fake-backend"
    fake_backend.num_qubits = 8
    fake_backend.status.return_value = MagicMock(pending_jobs=0)
    monkeypatch.setattr(rsb, "_select_backend", lambda service, min_qubits: fake_backend)

    fake_transpiled = MagicMock()
    fake_transpiled.depth.return_value = 2
    fake_transpiled.count_ops.return_value = {"cx": 5}
    fake_pm = MagicMock(run=MagicMock(return_value=fake_transpiled))

    qiskit_module = MagicMock()
    qiskit_transpiler = MagicMock()
    qiskit_preset_passmanagers = MagicMock(generate_preset_pass_manager=MagicMock(return_value=fake_pm))
    qiskit_module.transpiler = qiskit_transpiler
    qiskit_transpiler.preset_passmanagers = qiskit_preset_passmanagers

    monkeypatch.setitem(sys.modules, "qiskit", qiskit_module)
    monkeypatch.setitem(sys.modules, "qiskit.transpiler", qiskit_transpiler)
    monkeypatch.setitem(sys.modules, "qiskit.transpiler.preset_passmanagers", qiskit_preset_passmanagers)

    ibm_runtime = MagicMock()
    fake_job = MagicMock()
    fake_job.result.return_value = _FakeQiskitSamplerResult(fake_counts, execution_seconds=1.23)
    fake_job.job_id.return_value = "job-123"
    ibm_runtime.SamplerV2.return_value = MagicMock(run=MagicMock(return_value=fake_job))
    ibm_runtime.QiskitRuntimeService.return_value = MagicMock()
    monkeypatch.setitem(sys.modules, "qiskit_ibm_runtime", ibm_runtime)

    result = rsb.run_benchmark(
        dry_run=False, approved=True, now_utc="2026-09-01T08:00:00Z",
    )

    assert result["backend"] == "fake-backend"
    assert result["qpu_seconds"] == 1.23
    assert result["factor_found"] is None
    assert result["success"] is False


def _patch_common_circuit_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shared monkeypatching for circuit-building and backend selection."""
    fake_qc = MagicMock()
    fake_qc.depth.return_value = 4
    fake_qc.count_ops.return_value = {"cx": 10}
    monkeypatch.setattr(rsb, "_build_shor_circuit_n15", lambda n_count: (fake_qc, 8))
    monkeypatch.setattr(rsb, "_load_backend_snapshots", lambda *args: (_hardware_snapshot(),))
    monkeypatch.setattr(rsb, "_get_ibm_credentials", lambda: ("key", "instance"))

    fake_backend = MagicMock()
    fake_backend.name = "fake-backend"
    fake_backend.num_qubits = 8
    fake_backend.status.return_value = MagicMock(pending_jobs=0)
    monkeypatch.setattr(rsb, "_select_backend", lambda service, min_qubits: fake_backend)

    fake_transpiled = MagicMock()
    fake_transpiled.depth.return_value = 2
    fake_transpiled.count_ops.return_value = {"cx": 5}
    fake_pm = MagicMock(run=MagicMock(return_value=fake_transpiled))

    qiskit_module = MagicMock()
    qiskit_transpiler = MagicMock()
    qiskit_preset_passmanagers = MagicMock(generate_preset_pass_manager=MagicMock(return_value=fake_pm))
    qiskit_module.transpiler = qiskit_transpiler
    qiskit_transpiler.preset_passmanagers = qiskit_preset_passmanagers
    monkeypatch.setitem(sys.modules, "qiskit", qiskit_module)
    monkeypatch.setitem(sys.modules, "qiskit.transpiler", qiskit_transpiler)
    monkeypatch.setitem(sys.modules, "qiskit.transpiler.preset_passmanagers", qiskit_preset_passmanagers)


def test_run_shors_bench_job_wired_through_retry_supervisor(
    monkeypatch: pytest.MonkeyPatch, quantum_db_env,
) -> None:
    """The real backend submission must be wrapped in a Job and routed through
    RetrySupervisor — verified via a job_retry_status row being written, not
    by mocking backend.run()/Sampler.run() directly."""
    _patch_common_circuit_backend(monkeypatch)

    ibm_runtime = MagicMock()
    fake_job = MagicMock()
    fake_job.result.return_value = _FakeQiskitSamplerResult({"0010": 4096}, execution_seconds=2.0)
    fake_job.job_id.return_value = "job-456"
    ibm_runtime.SamplerV2.return_value = MagicMock(run=MagicMock(return_value=fake_job))
    ibm_runtime.QiskitRuntimeService.return_value = MagicMock()
    monkeypatch.setitem(sys.modules, "qiskit_ibm_runtime", ibm_runtime)

    result = rsb.run_benchmark(
        dry_run=False, approved=True, now_utc="2026-09-01T08:00:00Z",
    )

    assert result["provenance"]["configuration"]["depth"] == 4
    assert result["provenance"]["configuration"]["shots"] == rsb.N_SHOTS
    assert result["provenance"]["configuration"]["planner_result"]["status"] == "runnable_hardware_plan"
    rsb.persist_result(result)

    conn = init_db.get_connection()
    row = conn.execute(
        "SELECT status, backend FROM job_retry_status WHERE job_id = ?", ("shors-n15",)
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["status"] == "succeeded"
    assert row["backend"] == "ibm"


def test_run_shors_bench_permanent_job_failure_raises_and_records_status(
    monkeypatch: pytest.MonkeyPatch, quantum_db_env,
) -> None:
    """When run_fn (the wrapped backend submission) fails all retries, run_benchmark
    must raise so main()'s existing except-block exits non-zero, and the
    job_retry_status row must be FAILED with the job_id + error recorded."""
    _patch_common_circuit_backend(monkeypatch)

    def _always_raise(*_args, **_kwargs):
        raise RuntimeError("simulated permanent backend failure")

    ibm_runtime = MagicMock()
    ibm_runtime.SamplerV2.return_value = MagicMock(run=MagicMock(side_effect=_always_raise))
    ibm_runtime.QiskitRuntimeService.return_value = MagicMock()
    monkeypatch.setitem(sys.modules, "qiskit_ibm_runtime", ibm_runtime)

    # Avoid real backoff sleeps slowing the test down.
    monkeypatch.setattr(rsb.time, "sleep", lambda *_a, **_kw: None)
    import job_retry_supervisor
    monkeypatch.setattr(job_retry_supervisor.time, "sleep", lambda *_a, **_kw: None)

    with pytest.raises(RuntimeError, match="shors-n15"):
        rsb.run_benchmark(
            dry_run=False, approved=True, now_utc="2026-09-01T08:00:00Z",
        )

    conn = init_db.get_connection()
    row = conn.execute(
        "SELECT status, error_msg FROM job_retry_status WHERE job_id = ?", ("shors-n15",)
    ).fetchone()
    conn.close()

    assert row["status"] == "failed"
    assert "simulated permanent backend failure" in row["error_msg"]


def test_main_dashboard_regen_uses_static_mode_with_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """BFX-20260701: dashboard regen subprocess must pass --static and a timeout.

    Without --static, gen_benchmark_dashboard.py defaults to a long-running
    live server that never exits, hanging subprocess.run() forever and
    preventing the run_completed policy_events row from ever being logged.
    """
    fake_result = {
        "backend": "fake-backend",
        "qpu_seconds": 1.0,
        "factor_found": None,
        "success": False,
        "n_value": 15,
        "n_qubits": 8,
    }

    monkeypatch.setattr(rsb, "_parse_args", lambda: argparse.Namespace(
        n=15, max_qpu_seconds=rsb.MAX_QPU_SECONDS, dry_run=False,
        defer_reason="", manual_override_note="", approved=False, now_utc="",
    ))
    monkeypatch.setattr(rsb, "log_policy_event", MagicMock())
    monkeypatch.setattr(rsb, "run_benchmark", lambda **kwargs: fake_result)
    monkeypatch.setattr(rsb, "persist_result", lambda result: 1)
    monkeypatch.setattr(rsb, "print_db_row", MagicMock())

    fake_run = MagicMock()
    monkeypatch.setattr(rsb.subprocess, "run", fake_run)

    with pytest.raises(SystemExit):
        rsb.main()

    fake_run.assert_called_once()
    call_args = fake_run.call_args
    cmd_args = call_args.args[0]
    assert "--static" in cmd_args
    assert "--no-open" in cmd_args
    assert call_args.kwargs.get("timeout") == 120
