"""Tests for tools/run_shors_bench.py."""
from __future__ import annotations

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
