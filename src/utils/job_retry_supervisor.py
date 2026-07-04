"""Batch job retry supervisor for Qiskit Aer + IBM Quantum backend jobs.

FR-20260704-qiskit-aer-retry-supervisor

Library-level module (no CLI/dashboard). Enqueues a batch of simulation jobs
(local Aer or IBM Quantum backend), retries failures with exponential backoff
(1s/4s/16s, max 3 attempts), and persists status to `job_retry_status` in
quantumpsi.db.

A hard circuit-breaker cap on real IBM backend calls protects the free-tier
10min/month IBM Quantum quota from runaway retry loops. The cap is shared
across the whole batch run, not per-job.

Usage:
    from job_retry_supervisor import Job, RetrySupervisor
    from init_db import get_connection

    conn = get_connection()
    supervisor = RetrySupervisor(conn=conn)
    supervisor.enqueue(Job(job_id="aer-1", backend="aer", run_fn=my_aer_call))
    supervisor.enqueue(Job(job_id="ibm-1", backend="ibm", run_fn=my_ibm_call))
    supervisor.run_all()
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

_VALID_BACKENDS = ("aer", "ibm")
_DEFAULT_BACKOFF_SCHEDULE = (1, 4, 16)
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_IBM_CALL_CAP = 10


class JobStatus(str, Enum):
    """Lifecycle status of a supervised job."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class Job:
    """A single batch simulation job to be supervised.

    Attributes:
        job_id: Unique identifier for the job (must be unique per batch run).
        backend: Either "aer" (local Qiskit Aer) or "ibm" (IBM Quantum backend).
        run_fn: Zero-arg callable that executes the job. Should raise an
            exception on failure and return a result on success. Real IBM
            calls must be injected here by the caller — this module never
            imports qiskit_ibm_runtime itself.
    """

    job_id: str
    backend: str
    run_fn: Callable[[], Any]

    def __post_init__(self) -> None:
        if self.backend not in _VALID_BACKENDS:
            raise ValueError(
                f"backend must be one of {_VALID_BACKENDS!r}, got {self.backend!r}"
            )


class RetrySupervisor:
    """Supervises a batch of Aer/IBM jobs with retry + exponential backoff.

    Args:
        conn: An open sqlcipher3 connection to quantumpsi.db.
        sleep_fn: Callable invoked with the backoff delay in seconds between
            attempts. Injectable for tests (default: time.sleep).
        max_attempts: Maximum number of retries per job (in addition to the
            initial attempt) before marking it failed. Total tries per job
            is therefore max_attempts + 1.
        backoff_schedule: Delay in seconds before each retry attempt.
            Length must equal max_attempts.
        ibm_call_cap: Hard cap on the total number of real IBM backend calls
            (run_fn invocations for backend="ibm" jobs) across the whole
            batch run. Protects the IBM Quantum free-tier 10min/month quota
            from runaway retry loops. Once the cap is reached, any remaining
            IBM attempts are short-circuited to FAILED without invoking
            run_fn again.
    """

    def __init__(
        self,
        conn: Any,
        sleep_fn: Callable[[float], None] = time.sleep,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        backoff_schedule: tuple = _DEFAULT_BACKOFF_SCHEDULE,
        ibm_call_cap: int = _DEFAULT_IBM_CALL_CAP,
    ) -> None:
        self.conn = conn
        self.sleep_fn = sleep_fn
        self.max_attempts = max_attempts
        self.backoff_schedule = backoff_schedule
        self.ibm_call_cap = ibm_call_cap
        self._ibm_calls_made = 0
        self._queue: list[Job] = []

    def enqueue(self, job: Job) -> None:
        """Add a job to the batch and persist an initial PENDING row."""
        self._queue.append(job)
        self.conn.execute(
            """
            INSERT INTO job_retry_status
                (job_id, backend, status, attempt, max_attempts, updated_at)
            VALUES (?, ?, ?, 0, ?, datetime('now'))
            """,
            (job.job_id, job.backend, JobStatus.PENDING.value, self.max_attempts),
        )
        self.conn.commit()

    def run_all(self) -> None:
        """Execute every enqueued job, retrying with backoff as needed."""
        for job in self._queue:
            self._run_job(job)

    def _run_job(self, job: Job) -> None:
        total_tries = self.max_attempts + 1
        error_msg: Optional[str] = None
        for attempt in range(1, total_tries + 1):
            if job.backend == "ibm" and self._ibm_calls_made >= self.ibm_call_cap:
                error_msg = (
                    f"circuit breaker tripped: IBM call cap ({self.ibm_call_cap}) "
                    "reached for this batch run — refusing further real backend "
                    "calls to protect the IBM Quantum quota"
                )
                self._update_status(job, JobStatus.FAILED, attempt - 1, error_msg)
                return

            self._update_status(job, JobStatus.RUNNING, attempt, None)
            try:
                if job.backend == "ibm":
                    self._ibm_calls_made += 1
                job.run_fn()
                self._update_status(job, JobStatus.SUCCEEDED, attempt, None)
                return
            except Exception as exc:  # noqa: BLE001 — supervisor must catch all job errors
                error_msg = str(exc)
                if attempt <= self.max_attempts:
                    self._update_status(job, JobStatus.RETRYING, attempt, error_msg)
                    delay = self.backoff_schedule[attempt - 1]
                    self.sleep_fn(delay)

        self._update_status(job, JobStatus.FAILED, total_tries, error_msg)

    def _update_status(
        self,
        job: Job,
        status: JobStatus,
        attempt: int,
        error_msg: Optional[str],
    ) -> None:
        self.conn.execute(
            """
            UPDATE job_retry_status
            SET status = ?, attempt = ?, error_msg = ?, updated_at = datetime('now')
            WHERE job_id = ?
            """,
            (status.value, attempt, error_msg, job.job_id),
        )
        self.conn.commit()
