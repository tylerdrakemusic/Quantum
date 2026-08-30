"""
⟨ψ⟩Quantum — tools/fill_cache.py

Band-aware IBM Quantum bitstring cache filler.

Submits H-gate measurement circuits to IBM Quantum (free tier: 10 QPU-min/month)
and writes results to the ty_string_cache. Caps QPU execution time at
MAX_QPU_SECONDS to preserve remaining monthly quota for algorithm experiments.

Usage
-----
    # Scheduled (monthly, 1st of month 01:00 UTC via QuantumCacheFill_Monthly task):
    C:\\G\\python.exe tools\\fill_cache.py

    # Interactive / ad-hoc:
    C:\\G\\python.exe tools\\fill_cache.py --max-qpu-seconds 180 --dry-run

    # Check remaining bits in cache without running:
    C:\\G\\python.exe tools\\fill_cache.py --status

Output
------
    f:\\⟨ψ⟩Quantum\\qbackups\\ty_string_cache_<YYYYMMDD_HHMMSS>.txt  (timestamped backup)
    f:\⟨ψ⟩Quantum\src\data\liveCache\ty_string_cache.txt          (live, latest)

Environment
-----------
    IBM_CLOUD_API_KEY     — IBM Cloud API key (required). From cloud.ibm.com/iam/apikeys.
    IBM_QUANTUM_INSTANCE  — Instance CRN (required). From quantum.cloud.ibm.com → Instances.
    Both must be set as Windows System Environment Variables; never hardcode.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent   # f:\⟨ψ⟩Quantum\
sys.path.insert(0, str(_ROOT / "src" / "utils"))

import execution_policy
import cache_integrity

POLICY_ID = "quantum_cache_fill_monthly"
_BACKUP_DIR       = _ROOT / "qbackups"
_LIVE_DIR         = _ROOT / "src" / "data" / "liveCache"
_LIVE_CACHE       = _LIVE_DIR / "ty_string_cache.txt"
_CAPACITY_BASELINE = _LIVE_DIR / "ty_string_cache_capacity.txt"

# ---------------------------------------------------------------------------
# Constants — tune these to control IBM quota usage
# ---------------------------------------------------------------------------

# Total QPU execution time to consume before stopping gracefully.
# 3 minutes leaves 7 minutes for algorithm experiments.
DEFAULT_MAX_QPU_SECONDS: int = execution_policy.policy_qpu_cap_seconds(POLICY_ID, 180)

# H-gate circuit parameters — maximises bits per job.
# 127 qubits × 4096 shots = 520 192 bits per job.
# On ibm_fez (Eagle 156Q) each job takes ~5–30s QPU time.
N_QUBITS: int   = 127
N_SHOTS:  int   = 4096

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_logger = logging.getLogger("fill_cache")


# ---------------------------------------------------------------------------
# IBM Quantum helpers
# ---------------------------------------------------------------------------

def _get_ibm_credentials() -> tuple[str, str]:
    """Read IBM_CLOUD_API_KEY and IBM_QUANTUM_INSTANCE from environment."""
    key = os.environ.get("IBM_CLOUD_API_KEY", "").strip()
    instance = os.environ.get("IBM_QUANTUM_INSTANCE", "").strip()
    if not key:
        raise RuntimeError(
            "IBM_CLOUD_API_KEY environment variable is not set. "
            "Set it as a Windows System Environment Variable and restart your shell."
        )
    if not instance:
        raise RuntimeError(
            "IBM_QUANTUM_INSTANCE environment variable is not set. "
            "Set it to your instance CRN from quantum.cloud.ibm.com."
        )
    return key, instance


def _build_h_circuit(n_qubits: int):  # type: ignore[return]
    """Build a circuit of n_qubits Hadamard gates followed by measurement."""
    try:
        from qiskit import QuantumCircuit  # type: ignore[import]
    except ImportError:
        raise ImportError("qiskit is required: pip install qiskit qiskit-ibm-runtime")

    qc = QuantumCircuit(n_qubits, n_qubits)
    qc.h(range(n_qubits))
    qc.measure(range(n_qubits), range(n_qubits))
    return qc


def _get_backend(service):
    """Return the least-busy operational backend."""
    backends = service.backends(
        simulator=False,
        operational=True,
        min_num_qubits=N_QUBITS,
    )
    if not backends:
        raise RuntimeError(
            f"No operational IBM Quantum backends with >= {N_QUBITS} qubits available."
        )
    # Sort by pending jobs (least-busy first)
    backends.sort(key=lambda b: b.status().pending_jobs)
    chosen = backends[0]
    status = chosen.status()
    _logger.info(
        "Backend selected: %s  (%d qubits, %d pending jobs)",
        chosen.name, chosen.num_qubits, status.pending_jobs,
    )
    return chosen


def _counts_to_bitstrings(counts: dict[str, int]) -> list[str]:
    """Convert Qiskit counts dict to one bitstring per shot."""
    lines: list[str] = []
    for bitstring, count in counts.items():
        clean = bitstring.replace(" ", "")   # Qiskit may insert spaces
        lines.extend([clean] * count)
    return lines


def _ensure_policy_events_table(conn) -> None:
    """Create policy_events table for execution observability if missing."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS policy_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            event_time   TEXT    NOT NULL,
            policy_id    TEXT    NOT NULL,
            event_type   TEXT    NOT NULL,
            status       TEXT    NOT NULL,
            source       TEXT    NOT NULL,
            detail       TEXT,
            next_run_at  TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_policy_events_policy_time ON policy_events(policy_id, event_time)"
    )
    conn.commit()


def _log_policy_event(event_type: str, status: str, detail: str) -> None:
    """Persist one policy event for cache-fill observability."""
    import init_db

    conn = init_db.get_connection()
    _ensure_policy_events_table(conn)
    event_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """INSERT INTO policy_events
               (event_time, policy_id, event_type, status, source, detail, next_run_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            event_time,
            POLICY_ID,
            event_type,
            status,
            "tools/fill_cache.py",
            detail,
            execution_policy.next_run_iso(POLICY_ID),
        ),
    )
    conn.commit()
    conn.close()


def _with_elapsed_duration(detail: str, timer_start: float) -> str:
    """Append non-negative wall-clock duration to a policy-event detail."""
    elapsed_seconds = max(time.monotonic() - timer_start, 0.0)
    return f"{detail} elapsed_seconds={elapsed_seconds:.3f}"


# ---------------------------------------------------------------------------
# Status helper
# ---------------------------------------------------------------------------

def _print_status() -> None:
    """Print current cache state and exit."""
    if not _LIVE_CACHE.exists():
        print("Live cache: ABSENT  (quantum_rt will use secrets fallback)")
        return

    total_bits = 0
    lines = 0
    with open(_LIVE_CACHE, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped and all(c in "01" for c in stripped):
                total_bits += len(stripped)
                lines += 1

    print(f"Live cache: {_LIVE_CACHE}")
    print(f"  Bitstring lines : {lines:,}")
    print(f"  Total bits      : {total_bits:,}")
    print(f"  Approx bytes    : {total_bits // 8:,}")

    # Backups
    backups = sorted(_BACKUP_DIR.glob("ty_string_cache_*.txt"))
    print(f"\nTimestamped backups ({len(backups)} files):")
    for b in backups:
        print(f"  {b.name}  ({b.stat().st_size:,} bytes)")


def _persist_cache_fill(all_bitstrings: list[str]) -> int:
    """Snapshot the old cache, then atomically replace it with the new cache."""
    existing: list[str] = []
    if _LIVE_CACHE.exists():
        validation = cache_integrity.validate_cache(_LIVE_CACHE)
        if not validation.valid:
            quarantined = cache_integrity.quarantine_cache(_LIVE_CACHE, _BACKUP_DIR / "quarantine")
            _logger.warning("Malformed live cache quarantined: %s", quarantined)
        else:
            existing = [line.strip() for line in _LIVE_CACHE.read_text(encoding="utf-8").splitlines() if line.strip()]
    replacement = cache_integrity.atomic_replace_cache(
        _LIVE_CACHE,
        _BACKUP_DIR,
        existing + all_bitstrings,
    )
    capacity_bytes = _LIVE_CACHE.stat().st_size
    _CAPACITY_BASELINE.write_text(f"{capacity_bytes}\n", encoding="utf-8")

    _logger.info("Capacity baseline: %s  (%d bytes)", _CAPACITY_BASELINE, capacity_bytes)
    if replacement.backup_path:
        _logger.info("Backup written : %s  (%d bytes)", replacement.backup_path, replacement.backup_path.stat().st_size)
    _logger.info("Live cache     : %s", _LIVE_CACHE)
    return sum(len(b) for b in all_bitstrings)


def _extract_counts_from_sampler_result(result) -> dict[str, int]:
    """Return measurement counts from a Qiskit runtime Sampler result."""
    if hasattr(result, "get_counts") and callable(result.get_counts):
        counts = result.get_counts()
        if isinstance(counts, dict):
            return counts

    pub_result = result[0]
    data = pub_result.data
    creg_name = next(iter(vars(data)))
    return getattr(data, creg_name).get_counts()


def _job_status_row(conn, job_id: str):
    """Return the job_retry_status row (status, error_msg) for job_id."""
    return conn.execute(
        "SELECT status, error_msg FROM job_retry_status WHERE job_id = ?",
        (job_id,),
    ).fetchone()


# ---------------------------------------------------------------------------
# Main fill routine
# ---------------------------------------------------------------------------

def run_fill(max_qpu_seconds: int, dry_run: bool = False) -> int:
    """
    Submit H-gate jobs to IBM Quantum until max_qpu_seconds QPU time is consumed.

    Returns the total number of bits collected.
    """
    _logger.info("=== ⟨ψ⟩Quantum cache fill starting ===")
    _logger.info("QPU time cap : %d s (%d min)", max_qpu_seconds, max_qpu_seconds // 60)
    _logger.info("Circuit      : %d qubits × %d shots = %d bits/job",
                 N_QUBITS, N_SHOTS, N_QUBITS * N_SHOTS)
    _logger.info("Dry run      : %s", dry_run)

    if dry_run:
        _logger.info("DRY RUN — no IBM jobs will be submitted.")
        _logger.info("Would write to: %s", _LIVE_CACHE)
        return 0

    # ----- Import IBM runtime -----
    try:
        from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2 as Sampler  # type: ignore[import]
        from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager  # type: ignore[import]
    except ImportError:
        raise ImportError(
            "Required packages missing. Install with:\n"
            "    pip install qiskit qiskit-ibm-runtime"
        )

    api_key, instance = _get_ibm_credentials()

    _logger.info("Connecting to IBM Quantum …")
    service = QiskitRuntimeService(
        channel="ibm_quantum_platform",
        token=api_key,
        instance=instance,
    )

    backend = _get_backend(service)
    qc = _build_h_circuit(N_QUBITS)

    # Transpile once for the target backend
    _logger.info("Transpiling circuit for backend …")
    pm = generate_preset_pass_manager(optimization_level=1, backend=backend)
    transpiled = pm.run(qc)

    # ----- Job loop — supervised via RetrySupervisor (retry/backoff + IBM call cap) -----
    import init_db
    from job_retry_supervisor import Job, JobStatus, RetrySupervisor

    all_bitstrings: list[str] = []
    jobs_submitted = 0
    jobs_completed = 0
    qpu_seconds_consumed = 0.0
    job_failed = False
    failed_job_id: Optional[str] = None
    failed_error_msg: Optional[str] = None

    sampler = Sampler(backend)

    conn = init_db.get_connection()
    supervisor = RetrySupervisor(conn=conn)

    while qpu_seconds_consumed < max_qpu_seconds:
        remaining = max_qpu_seconds - qpu_seconds_consumed
        jobs_submitted += 1
        job_id = f"fill-cache-{jobs_submitted}"
        _logger.info(
            "Submitting job %d  (QPU used: %.1fs / %ds, remaining: %.1fs)",
            jobs_submitted, qpu_seconds_consumed, max_qpu_seconds, remaining,
        )

        outcome: dict = {}

        def _run_fn(sampler=sampler, transpiled=transpiled, outcome=outcome) -> None:
            job = sampler.run([transpiled], shots=N_SHOTS)
            poll_start = time.monotonic()
            result = job.result()
            wall_elapsed = time.monotonic() - poll_start
            try:
                usage = result.metadata.get("execution", {})
                qpu_elapsed = float(usage.get("execution_spans_seconds", wall_elapsed))
            except (AttributeError, TypeError, ValueError):
                qpu_elapsed = wall_elapsed
            counts = _extract_counts_from_sampler_result(result)
            outcome["qpu_elapsed"] = qpu_elapsed
            outcome["bitstrings"] = _counts_to_bitstrings(counts)

        supervisor.enqueue(Job(job_id=job_id, backend="ibm", run_fn=_run_fn))
        supervisor.run_all()
        supervisor._queue.clear()

        row = _job_status_row(conn, job_id)
        if row is not None and row["status"] == JobStatus.SUCCEEDED.value:
            qpu_elapsed = outcome["qpu_elapsed"]
            bitstrings = outcome["bitstrings"]
            qpu_seconds_consumed += qpu_elapsed
            jobs_completed += 1
            all_bitstrings.extend(bitstrings)

            _logger.info(
                "Job %d done — %.1fs QPU, %d bitstrings, total bits so far: %d",
                jobs_completed, qpu_elapsed, len(bitstrings),
                sum(len(b) for b in all_bitstrings),
            )
        else:
            job_failed = True
            failed_job_id = job_id
            failed_error_msg = row["error_msg"] if row is not None else "unknown error"
            _logger.warning(
                "Job %s failed (job_id=%s): %s — stopping.",
                jobs_submitted, job_id, failed_error_msg,
            )
            break

    conn.close()

    # ----- Write output -----
    total_bits = sum(len(b) for b in all_bitstrings)
    _logger.info("=== Fill complete ===")
    _logger.info("Jobs submitted : %d", jobs_submitted)
    _logger.info("Jobs completed : %d", jobs_completed)
    _logger.info("QPU time used  : %.1f s", qpu_seconds_consumed)
    _logger.info("Total bits     : %d", total_bits)

    if job_failed:
        _logger.error(
            "Permanent job failure — job_id=%s error=%s (partial results preserved: %d bits)",
            failed_job_id, failed_error_msg, total_bits,
        )

    if total_bits == 0:
        _logger.warning("No bits collected — cache not updated.")
        if job_failed:
            raise RuntimeError(
                f"fill_cache job {failed_job_id} failed permanently: {failed_error_msg}"
            )
        return 0

    persisted_bits = _persist_cache_fill(all_bitstrings)
    if job_failed:
        raise RuntimeError(
            f"fill_cache job {failed_job_id} failed permanently: {failed_error_msg} "
            f"(partial success preserved: {persisted_bits} bits written to cache)"
        )
    return persisted_bits


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Band-aware IBM Quantum bitstring cache filler for ⟨ψ⟩Quantum.",
    )
    parser.add_argument(
        "--max-qpu-seconds",
        type=int,
        default=DEFAULT_MAX_QPU_SECONDS,
        metavar="SECONDS",
        help=f"QPU execution time cap in seconds (default: {DEFAULT_MAX_QPU_SECONDS} = 3 min). "
             "Lower values preserve more monthly quota for experiments.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Connect to IBM, select backend, but do not submit jobs.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print current cache state and exit.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    timer_start = time.monotonic()

    if args.status:
        _print_status()
        sys.exit(0)

    _log_policy_event(
        event_type="run_started",
        status="started",
        detail=(
            f"Started cache fill; schedule={execution_policy.schedule_label(POLICY_ID)}; "
            f"qpu_cap={args.max_qpu_seconds}s"
        ),
    )

    try:
        bits = run_fill(
            max_qpu_seconds=args.max_qpu_seconds,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            _log_policy_event(
                event_type="run_completed",
                status="skipped",
                detail=_with_elapsed_duration(
                    "Dry-run executed; no IBM submissions and no cache update.",
                    timer_start,
                ),
            )
        elif bits > 0:
            _logger.info("Cache fill successful. Run with --status to verify.")
            _log_policy_event(
                event_type="run_completed",
                status="succeeded",
                detail=_with_elapsed_duration(
                    f"Cache fill completed with {bits} bits collected.",
                    timer_start,
                ),
            )
        else:
            _log_policy_event(
                event_type="run_completed",
                status="failed",
                detail=_with_elapsed_duration(
                    "Cache fill completed with zero bits; cache not updated.",
                    timer_start,
                ),
            )
        sys.exit(0)
    except KeyboardInterrupt:
        _logger.info("Interrupted by user — partial results discarded.")
        _log_policy_event(
            event_type="run_completed",
            status="deferred",
            detail=_with_elapsed_duration("Cache fill interrupted by user.", timer_start),
        )
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        _logger.error("fill_cache.py failed: %s", exc)
        _log_policy_event(
            event_type="run_completed",
            status="failed",
            detail=_with_elapsed_duration(f"Cache fill failed: {exc}", timer_start),
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
