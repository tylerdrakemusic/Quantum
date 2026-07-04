"""
Unit tests for src/utils/job_retry_supervisor.py (FR-20260704-qiskit-aer-retry-supervisor)

Covers:
  - Enqueuing a batch of Aer + IBM jobs
  - Retry/backoff logic (max 3 attempts, 1s/4s/16s schedule)
  - DB persistence of job status to job_retry_status (mocked encrypted DB)
  - IBM circuit breaker: hard cap on real backend calls, no runaway quota usage
  - No real IBM Quantum API calls are made in tests (run_fn is always mocked)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src" / "utils") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src" / "utils"))

import init_db
from job_retry_supervisor import (
    Job,
    JobStatus,
    RetrySupervisor,
)


@pytest.fixture
def quantum_db_env(tmp_path, monkeypatch):
    db_path = tmp_path / "quantumpsi.db"
    monkeypatch.setenv("QUANTUM_DB_PATH", str(db_path))
    monkeypatch.setenv("QUANTUM_DB_KEY", "testkey")
    # init_db caches DB_PATH at module import time, so the env var alone
    # won't take effect on an already-imported module — patch it directly.
    monkeypatch.setattr(init_db, "DB_PATH", db_path)
    init_db.init_db()
    yield db_path


def _sleepless(seconds):
    """Fake sleep_fn — records nothing itself, just avoids real waiting."""
    return None


def test_enqueue_batch_aer_and_ibm_jobs_creates_pending_rows(quantum_db_env):
    conn = init_db.get_connection()
    supervisor = RetrySupervisor(conn=conn, sleep_fn=_sleepless)

    aer_job = Job(job_id="aer-1", backend="aer", run_fn=lambda: "ok")
    ibm_job = Job(job_id="ibm-1", backend="ibm", run_fn=lambda: "ok")

    supervisor.enqueue(aer_job)
    supervisor.enqueue(ibm_job)

    rows = conn.execute(
        "SELECT job_id, backend, status FROM job_retry_status ORDER BY job_id"
    ).fetchall()
    conn.close()

    assert [dict(r) for r in rows] == [
        {"job_id": "aer-1", "backend": "aer", "status": JobStatus.PENDING.value},
        {"job_id": "ibm-1", "backend": "ibm", "status": JobStatus.PENDING.value},
    ]


def test_job_succeeds_on_first_attempt(quantum_db_env):
    conn = init_db.get_connection()
    supervisor = RetrySupervisor(conn=conn, sleep_fn=_sleepless)

    calls = []
    job = Job(job_id="aer-ok", backend="aer", run_fn=lambda: calls.append(1) or "result")
    supervisor.enqueue(job)
    supervisor.run_all()

    row = conn.execute(
        "SELECT status, attempt FROM job_retry_status WHERE job_id = ?", ("aer-ok",)
    ).fetchone()
    conn.close()

    assert len(calls) == 1
    assert row["status"] == JobStatus.SUCCEEDED.value
    assert row["attempt"] == 1


def test_job_retries_with_exponential_backoff_then_succeeds(quantum_db_env):
    conn = init_db.get_connection()
    sleeps = []
    supervisor = RetrySupervisor(conn=conn, sleep_fn=sleeps.append)

    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient failure")
        return "ok"

    job = Job(job_id="aer-flaky", backend="aer", run_fn=flaky)
    supervisor.enqueue(job)
    supervisor.run_all()

    row = conn.execute(
        "SELECT status, attempt FROM job_retry_status WHERE job_id = ?", ("aer-flaky",)
    ).fetchone()
    conn.close()

    assert attempts["n"] == 3
    assert sleeps == [1, 4]
    assert row["status"] == JobStatus.SUCCEEDED.value
    assert row["attempt"] == 3


def test_job_exhausts_retries_and_marks_failed(quantum_db_env):
    conn = init_db.get_connection()
    sleeps = []
    supervisor = RetrySupervisor(conn=conn, sleep_fn=sleeps.append)

    def always_fails():
        raise RuntimeError("permanent failure")

    job = Job(job_id="aer-dead", backend="aer", run_fn=always_fails)
    supervisor.enqueue(job)
    supervisor.run_all()

    row = conn.execute(
        "SELECT status, attempt, error_msg FROM job_retry_status WHERE job_id = ?",
        ("aer-dead",),
    ).fetchone()
    conn.close()

    assert sleeps == [1, 4, 16]
    assert row["status"] == JobStatus.FAILED.value
    assert row["attempt"] == 4
    assert "permanent failure" in row["error_msg"]


def test_default_backoff_schedule_is_1_4_16(quantum_db_env):
    conn = init_db.get_connection()
    supervisor = RetrySupervisor(conn=conn, sleep_fn=_sleepless)
    conn.close()
    assert supervisor.backoff_schedule == (1, 4, 16)
    assert supervisor.max_attempts == 3


def test_ibm_circuit_breaker_caps_real_backend_calls(quantum_db_env):
    """IBM's 10min/month quota must never be at risk from a retry loop.

    With a hard cap of 2 real IBM calls total across the whole batch run,
    a third IBM job (or further retries) must be short-circuited to
    'failed' WITHOUT invoking run_fn again.
    """
    conn = init_db.get_connection()
    sleeps = []
    call_count = {"n": 0}

    def always_fails_ibm():
        call_count["n"] += 1
        raise RuntimeError("ibm backend error")

    supervisor = RetrySupervisor(
        conn=conn, sleep_fn=sleeps.append, ibm_call_cap=2
    )
    job = Job(job_id="ibm-loop", backend="ibm", run_fn=always_fails_ibm)
    supervisor.enqueue(job)
    supervisor.run_all()

    row = conn.execute(
        "SELECT status, attempt, error_msg FROM job_retry_status WHERE job_id = ?",
        ("ibm-loop",),
    ).fetchone()
    conn.close()

    # circuit breaker trips after 2 real calls, well short of the 3-attempt max
    assert call_count["n"] == 2
    assert row["status"] == JobStatus.FAILED.value
    assert "circuit breaker" in row["error_msg"].lower()


def test_ibm_circuit_breaker_shared_across_multiple_jobs(quantum_db_env):
    """Cap applies to the whole batch, not per-job."""
    conn = init_db.get_connection()
    call_count = {"n": 0}

    def always_fails_ibm():
        call_count["n"] += 1
        raise RuntimeError("ibm backend error")

    supervisor = RetrySupervisor(conn=conn, sleep_fn=lambda s: None, ibm_call_cap=1)
    supervisor.enqueue(Job(job_id="ibm-a", backend="ibm", run_fn=always_fails_ibm))
    supervisor.enqueue(Job(job_id="ibm-b", backend="ibm", run_fn=always_fails_ibm))
    supervisor.run_all()

    rows = conn.execute(
        "SELECT job_id, status, error_msg FROM job_retry_status ORDER BY job_id"
    ).fetchall()
    conn.close()

    # Only 1 real call total permitted across both jobs combined
    assert call_count["n"] == 1
    for row in rows:
        assert row["status"] == JobStatus.FAILED.value


def test_aer_jobs_are_not_subject_to_ibm_circuit_breaker(quantum_db_env):
    conn = init_db.get_connection()
    call_count = {"n": 0}

    def always_fails():
        call_count["n"] += 1
        raise RuntimeError("aer failure")

    supervisor = RetrySupervisor(conn=conn, sleep_fn=lambda s: None, ibm_call_cap=0)
    supervisor.enqueue(Job(job_id="aer-x", backend="aer", run_fn=always_fails))
    supervisor.run_all()

    row = conn.execute(
        "SELECT status, attempt FROM job_retry_status WHERE job_id = ?", ("aer-x",)
    ).fetchone()
    conn.close()

    # Aer jobs still get all 4 tries (1 initial + 3 retries) even though ibm_call_cap == 0
    assert call_count["n"] == 4
    assert row["status"] == JobStatus.FAILED.value
    assert row["attempt"] == 4


def test_invalid_backend_raises_value_error(quantum_db_env):
    conn = init_db.get_connection()
    with pytest.raises(ValueError):
        Job(job_id="bad", backend="not-a-backend", run_fn=lambda: None)
    conn.close()


def test_no_real_ibm_quantum_api_calls_are_ever_made(quantum_db_env):
    """Sanity check: this whole test module never imports qiskit_ibm_runtime
    or touches a real IBM Quantum service. All IBM jobs use plain mocked
    run_fn callables."""
    assert "qiskit_ibm_runtime" not in sys.modules
