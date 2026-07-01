"""Tests for tools/run_vqe_bench.py (BFX-20260630-quantum-vqe-monthly-degraded)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "tools"))

import run_vqe_bench as rvb  # noqa: E402


class _FakeConn:
    """Minimal in-memory stand-in for a sqlcipher3 connection used by policy_events tests."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self._rows: list[dict] = []

    def execute(self, sql: str, params: tuple = ()):
        self.executed.append((sql, params))
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("INSERT INTO POLICY_EVENTS"):
            keys = [
                "event_time", "policy_id", "event_type", "status",
                "source", "detail", "next_run_at",
            ]
            self._rows.append(dict(zip(keys, params)))
        return self

    def fetchall(self):
        return self._rows

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_log_policy_event_writes_policy_events_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """log_policy_event() should insert a policy_events row for vqe_monthly_benchmark."""
    fake_conn = _FakeConn()
    fake_init_db = MagicMock(get_connection=MagicMock(return_value=fake_conn))
    monkeypatch.setitem(sys.modules, "init_db", fake_init_db)

    rvb.log_policy_event(event_type="run_started", status="started", detail="test start")

    assert len(fake_conn._rows) == 1
    row = fake_conn._rows[0]
    assert row["policy_id"] == "vqe_monthly_benchmark"
    assert row["event_type"] == "run_started"
    assert row["status"] == "started"


def test_wall_clock_guard_aborts_remaining_molecules(monkeypatch: pytest.MonkeyPatch) -> None:
    """If a molecule run pushes elapsed time to/over the cap, remaining molecules must abort."""
    calls: list[str] = []

    def fake_run_vqe(molecule: str, backend_label: str = "aer_statevector", **_kwargs) -> dict:
        calls.append(molecule)
        return {
            "molecule": molecule, "n_qubits": 4, "n_pauli_terms": 10, "n_params": 2,
            "final_energy": -1.0, "fci_reference": -1.0, "delta_fci": 0.0,
            "delta_target": 0.0, "ac_window": 1.6e-3, "ac_met": True,
            "evals": 5, "wall_sec": 1.0, "backend": backend_label, "timestamp": "2026-06-30T00:00:00",
        }

    events: list[tuple[str, str, str]] = []
    monkeypatch.setattr(rvb, "_bench_vqe_run_vqe", fake_run_vqe)
    monkeypatch.setattr(
        rvb, "log_policy_event",
        lambda event_type, status, detail: events.append((event_type, status, detail)),
    )

    # Simulate monotonic clock: first molecule takes the whole budget.
    times = iter([0.0, 0.0, 100.0, 100.0])
    monkeypatch.setattr(rvb.time, "monotonic", lambda: next(times))

    results = rvb.run_all_molecules(["h2", "lih"], backend_label="aer_statevector", max_qpu_seconds=50)

    assert calls == ["h2"]
    assert any(status == "deferred" for _, status, _ in events)


def test_budget_check_falls_back_to_aer_when_shared_budget_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    """If cache-fill + Shor's already consumed the shared 600s tier this month, qpu request falls back to aer."""
    now_month = "2026-06"

    def fake_events_this_month(conn, policy_id: str, month_key: str):
        if policy_id in ("quantum_cache_fill_monthly", "shors_monthly_benchmark"):
            return [{"status": "succeeded"}]
        return []

    monkeypatch.setattr(rvb, "_succeeded_events_this_month", fake_events_this_month)

    available = rvb.available_qpu_budget_seconds(conn=MagicMock(), month_key=now_month)
    assert available < rvb.MAX_QPU_SECONDS

    backend, deferred_detail = rvb.resolve_backend_choice(
        requested="qpu", conn=MagicMock(), month_key=now_month,
    )
    assert backend == "aer"
    assert deferred_detail is not None


def test_run_all_molecules_qpu_builds_estimator_and_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """When backend_label is the QPU label, run_all_molecules must build an
    EstimatorV2 (mocked here — no real job submission) and pass it + the
    selected backend through to bench_vqe.run_vqe."""
    fake_estimator = MagicMock(name="EstimatorV2")
    fake_backend = MagicMock(name="ibm_backend")
    build_calls: list[list[str]] = []

    def fake_build_qpu_estimator(molecules: list[str]):
        build_calls.append(molecules)
        return fake_estimator, fake_backend

    received: list[dict] = []

    def fake_run_vqe(molecule: str, backend_label: str = "aer_statevector", **kwargs) -> dict:
        received.append({"molecule": molecule, "backend_label": backend_label, **kwargs})
        return {
            "molecule": molecule, "n_qubits": 4, "n_pauli_terms": 10, "n_params": 2,
            "final_energy": -1.0, "fci_reference": -1.0, "delta_fci": 0.0,
            "delta_target": 0.0, "ac_window": 1.6e-3, "ac_met": True,
            "evals": 5, "wall_sec": 1.0, "backend": backend_label, "timestamp": "2026-06-30T00:00:00",
        }

    monkeypatch.setattr(rvb, "_build_qpu_estimator", fake_build_qpu_estimator)
    monkeypatch.setattr(rvb, "_bench_vqe_run_vqe", fake_run_vqe)
    monkeypatch.setattr(rvb, "log_policy_event", lambda **_kwargs: None)

    results = rvb.run_all_molecules(
        ["h2"], backend_label="ibm_qpu_estimator_v2", max_qpu_seconds=600,
    )

    assert build_calls == [["h2"]]
    assert len(results) == 1
    assert received[0]["estimator"] is fake_estimator
    assert received[0]["qpu_backend"] is fake_backend
