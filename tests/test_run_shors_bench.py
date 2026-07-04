"""Tests for tools/run_shors_bench.py."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "tools"))
sys.path.insert(0, str(_PROJECT_ROOT / "src" / "utils"))

import init_db  # noqa: E402
import run_shors_bench as rsb  # noqa: E402


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


def test_run_shors_bench_uses_result_get_counts(monkeypatch: pytest.MonkeyPatch, quantum_db_env) -> None:
    """The benchmark should use result.get_counts() when supported."""
    fake_counts = {"0010": 4096}
    fake_qc = MagicMock()
    fake_qc.depth.return_value = 4
    fake_qc.count_ops.return_value = {"cx": 10}

    monkeypatch.setattr(rsb, "_build_shor_circuit_n15", lambda n_count: (fake_qc, 8))
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

    result = rsb.run_benchmark(dry_run=False)

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

    rsb.run_benchmark(dry_run=False)

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
        rsb.run_benchmark(dry_run=False)

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
        defer_reason="", manual_override_note="",
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
