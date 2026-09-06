from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "utils"))

import init_db
from quantum_toolkit.benchmark_replay import (
    TOLERANCE_VERSION,
    capture_runtime_result,
    compare_metrics,
    persist_replay,
    replay_local,
    resubmission_decision,
    resubmit_runtime_job,
)


def test_comparison_records_family_tolerance_version_and_status() -> None:
    comparison = compare_metrics(
        "vqe",
        expected={"energy": -1.0},
        actual={"energy": -0.99},
    )

    assert comparison["status"] == "pass"
    assert comparison["family"] == "vqe"
    assert comparison["tolerance_version"] == TOLERANCE_VERSION
    assert comparison["metrics"]["energy"]["absolute_error"] == pytest.approx(0.01)


def test_comparison_classifies_tolerance_failure_without_composite_score() -> None:
    comparison = compare_metrics(
        "qaoa",
        expected={"approximation_ratio": 0.9},
        actual={"approximation_ratio": 0.7},
    )

    assert comparison["status"] == "tolerance_failure"
    assert "composite_score" not in comparison


def test_seeded_replay_is_repeatable_and_records_outcome() -> None:
    def execute(seed: int) -> dict[str, float | str]:
        return {"status": "pass", "energy": round(seed / 1000, 3)}

    first = replay_local("qec", seed=17, execute=execute)
    second = replay_local("qec", seed=17, execute=execute)

    assert first == second
    assert first["outcome"] == "pass"
    assert first["seed"] == 17
    assert first["tolerance_version"] == TOLERANCE_VERSION


def test_runtime_capture_redacts_credentials_and_bounds_resubmission() -> None:
    captured = capture_runtime_result(
        {
            "backend": "ibm_fez",
            "provider": "ibm_quantum",
            "job_id": "job-7",
            "api_key": "secret",
            "execution": {"retry_count": 1, "status": "failed"},
        }
    )

    assert "api_key" not in captured
    assert captured["job_id"] == "job-7"
    assert resubmission_decision(captured, approved=True, quota_remaining_seconds=30)["status"] == "approved"
    assert resubmission_decision(captured, approved=False, quota_remaining_seconds=30)["status"] == "approval_required"
    assert resubmission_decision(captured, approved=True, quota_remaining_seconds=0)["status"] == "quota_blocked"


def test_approved_runtime_resubmission_executes_bounded_callback() -> None:
    captured = capture_runtime_result({"execution": {"status": "failed"}, "job_id": "job-8"})
    attempts: list[str] = []

    result = resubmit_runtime_job(
        captured,
        approved=True,
        quota_remaining_seconds=30,
        submit=lambda: attempts.append("submitted") or "new-job-8",
    )

    assert result == {"status": "submitted", "new_job_id": "new-job-8", "attempt": 1}
    assert attempts == ["submitted"]


@pytest.fixture
def provenance_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "quantumpsi.db"
    monkeypatch.setenv("QUANTUM_DB_PATH", str(db_path))
    monkeypatch.setenv("QUANTUM_DB_KEY", "testkey")
    monkeypatch.setattr(init_db, "DB_PATH", db_path)
    init_db.init_db()
    yield db_path


def test_persist_replay_keeps_legacy_rows_and_stores_normalized_record(provenance_db: Path) -> None:
    conn = init_db.get_connection()
    conn.execute(
        "INSERT INTO benchmarks (algorithm, total_time_sec, required_qubits, n_value, backend, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("legacy-shor", 1.0, 4, 15, "old-aer", "2024-01-01T00:00:00Z"),
    )
    replay = replay_local("shor", seed=3, execute=lambda seed: {"status": "unavailable"})

    row_id = persist_replay(conn, replay, run_id="shor-replay-3")
    stored = conn.execute(
        "SELECT run_id, outcome, seed, tolerance_version FROM benchmark_replays WHERE id = ?",
        (row_id,),
    ).fetchone()
    legacy = conn.execute(
        "SELECT algorithm, backend FROM benchmarks WHERE algorithm = ?", ("legacy-shor",)
    ).fetchone()
    conn.close()

    assert dict(stored) == {
        "run_id": "shor-replay-3",
        "outcome": "unavailable",
        "seed": 3,
        "tolerance_version": TOLERANCE_VERSION,
    }
    assert dict(legacy) == {"algorithm": "legacy-shor", "backend": "old-aer"}