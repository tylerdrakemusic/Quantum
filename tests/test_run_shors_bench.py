"""Tests for tools/run_shors_bench.py."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "tools"))

import run_shors_bench as rsb  # noqa: E402


class _FakeQiskitSamplerResult:
    def __init__(self, counts: dict[str, int], execution_seconds: float = 1.23) -> None:
        self.metadata = {"execution": {"execution_spans_seconds": execution_seconds}}
        self._counts = counts

    def get_counts(self) -> dict[str, int]:
        return self._counts

    def __getitem__(self, item):
        raise TypeError("'Result' object is not subscriptable")


def test_run_shors_bench_uses_result_get_counts(monkeypatch: pytest.MonkeyPatch) -> None:
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
