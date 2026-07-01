#!/usr/bin/env python3
"""
⟨ψ⟩Quantum — tools/run_vqe_bench.py

Monthly VQE QPU benchmark runner (BFX-20260630-quantum-vqe-monthly-degraded).

Wraps tools/bench_vqe.py's run_vqe() with the same policy_events
observability pattern used by tools/run_shors_bench.py, adds a hard
wall-clock guard against the configured QPU cap, and adds a cross-policy
shared-budget check so a real-QPU request cannot silently exceed the
600s/month IBM free tier already partially consumed by
QuantumCacheFill_Monthly (180s) and ShorsMonthlyBench (300s).

Usage
-----
    C:\\G\\python.exe tools\\run_vqe_bench.py --molecule all
    C:\\G\\python.exe tools\\run_vqe_bench.py --molecule h2 --backend qpu
    C:\\G\\python.exe tools\\run_vqe_bench.py --dry-run

Environment
-----------
    QUANTUM_DB_KEY  — SQLCipher key for quantumpsi.db (required)
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent   # f:\⟨ψ⟩Quantum\
sys.path.insert(0, str(_ROOT / "src" / "utils"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── Constants ──────────────────────────────────────────────────────────────
POLICY_ID = "vqe_monthly_benchmark"
OTHER_MONTHLY_POLICIES = ("quantum_cache_fill_monthly", "shors_monthly_benchmark")
SHARED_MONTHLY_BUDGET_SECONDS = 600

import execution_policy  # noqa: E402

MAX_QPU_SECONDS: int = execution_policy.policy_qpu_cap_seconds(POLICY_ID, 600)

from bench_vqe import run_vqe as _bench_vqe_run_vqe  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_log = logging.getLogger("run_vqe_bench")


# ═══════════════════════════════════════════════════════════════════════════
# policy_events helpers (mirrors tools/run_shors_bench.py)
# ═══════════════════════════════════════════════════════════════════════════

def _ensure_policy_events_table(conn) -> None:
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


def _record_policy_event(
    conn, *, policy_id: str, event_type: str, status: str,
    source: str, detail: str, next_run_at: str,
) -> None:
    event_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """INSERT INTO policy_events
               (event_time, policy_id, event_type, status, source, detail, next_run_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (event_time, policy_id, event_type, status, source, detail, next_run_at),
    )
    conn.commit()


def log_policy_event(*, event_type: str, status: str, detail: str) -> None:
    """Persist one benchmark policy event for UI observability."""
    import init_db

    next_run_at = execution_policy.next_run_iso(POLICY_ID)
    conn = init_db.get_connection()
    _ensure_policy_events_table(conn)
    _record_policy_event(
        conn,
        policy_id=POLICY_ID,
        event_type=event_type,
        status=status,
        source="tools/run_vqe_bench.py",
        detail=detail,
        next_run_at=next_run_at,
    )
    conn.close()


# IBM Quantum helpers (mirrors tools/run_shors_bench.py's inline pattern)
# ═══════════════════════════════════════════════════════════════════════════

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


def _select_backend(service, min_qubits: int):
    """Return the least-busy operational backend with >= min_qubits qubits."""
    backends = service.backends(
        simulator=False,
        operational=True,
        min_num_qubits=min_qubits,
    )
    if not backends:
        raise RuntimeError(
            f"No operational IBM Quantum backends with >= {min_qubits} qubits."
        )
    backends.sort(key=lambda b: b.status().pending_jobs)
    chosen = backends[0]
    status = chosen.status()
    _log.info(
        "Backend selected: %s  (%d qubits, %d pending jobs)",
        chosen.name, chosen.num_qubits, status.pending_jobs,
    )
    return chosen


def _build_qpu_estimator(molecules: list[str]):
    """Connect to IBM Quantum, select a backend sized for the largest molecule
    in `molecules`, and return (estimator, backend)."""
    from qiskit_ibm_runtime import QiskitRuntimeService, EstimatorV2 as Estimator

    # H2 (ParityMapper, tapered) needs fewer qubits than LiH — size for the max.
    min_qubits = max(
        MOLECULE_QUBIT_HINTS.get(m, 4) for m in molecules
    ) if molecules else 4

    api_key, instance = _get_ibm_credentials()
    _log.info("Connecting to IBM Quantum platform …")
    service = QiskitRuntimeService(
        channel="ibm_quantum_platform",
        token=api_key,
        instance=instance,
    )
    backend = _select_backend(service, min_qubits=min_qubits)
    estimator = Estimator(backend)
    return estimator, backend


# ── Rough post-tapering qubit counts, used only to size the QPU backend pick.
MOLECULE_QUBIT_HINTS: dict[str, int] = {"h2": 2, "lih": 10}


# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════
# Cross-policy shared monthly QPU budget check
# ═══════════════════════════════════════════════════════════════════════════

def _succeeded_events_this_month(conn, policy_id: str, month_key: str) -> list[dict]:
    """Return policy_events rows for `policy_id` this month with status succeeded."""
    rows = conn.execute(
        """SELECT status, event_time FROM policy_events
               WHERE policy_id = ? AND event_type = 'run_completed'
                     AND status = 'succeeded' AND substr(event_time, 1, 7) = ?""",
        (policy_id, month_key),
    ).fetchall()
    return [dict(r) if not isinstance(r, dict) else r for r in rows]


def available_qpu_budget_seconds(conn, month_key: str | None = None) -> float:
    """Return remaining shared free-tier QPU seconds available for VQE this month."""
    month_key = month_key or datetime.now(timezone.utc).strftime("%Y-%m")
    consumed = 0
    for policy_id in OTHER_MONTHLY_POLICIES:
        events = _succeeded_events_this_month(conn, policy_id, month_key)
        if events:
            consumed += execution_policy.policy_qpu_cap_seconds(policy_id, 0)
    return SHARED_MONTHLY_BUDGET_SECONDS - consumed


def resolve_backend_choice(
    requested: str, conn, month_key: str | None = None,
    required_seconds: int = MAX_QPU_SECONDS,
) -> tuple[str, str | None]:
    """Resolve the effective backend ('aer' or 'qpu').

    Returns (backend, deferred_detail). deferred_detail is non-None when a
    real-QPU request was downgraded to aer because the shared monthly
    free-tier budget already consumed by the other two policies leaves less
    than `required_seconds` available for this VQE run.
    """
    if requested != "qpu":
        return requested, None

    available = available_qpu_budget_seconds(conn, month_key)
    if available < required_seconds:
        detail = (
            f"Shared monthly QPU budget insufficient ({SHARED_MONTHLY_BUDGET_SECONDS}s tier; "
            f"only {available:.0f}s remaining after cache-fill/Shor's, need {required_seconds}s) "
            f"— falling back to Aer."
        )
        return "aer", detail
    return "qpu", None


# ═══════════════════════════════════════════════════════════════════════════
# Wall-clock guarded multi-molecule runner
# ═══════════════════════════════════════════════════════════════════════════

def run_all_molecules(
    molecules: list[str], backend_label: str, max_qpu_seconds: int,
) -> list[dict]:
    """Run each molecule via bench_vqe.run_vqe(), aborting if the hard wall-clock
    cap would be exceeded before starting the next molecule."""
    results: list[dict] = []
    wall_start = time.monotonic()

    estimator = None
    qpu_backend = None
    if backend_label == "ibm_qpu_estimator_v2":
        estimator, qpu_backend = _build_qpu_estimator(molecules)

    for i, molecule in enumerate(molecules):
        elapsed = time.monotonic() - wall_start
        if elapsed >= max_qpu_seconds:
            remaining = molecules[i:]
            detail = (
                f"Wall-clock cap ({max_qpu_seconds}s) reached after {elapsed:.1f}s — "
                f"aborting remaining molecules: {', '.join(remaining)}"
            )
            _log.warning(detail)
            log_policy_event(event_type="run_deferred", status="deferred", detail=detail)
            break

        result = _bench_vqe_run_vqe(
            molecule, backend_label=backend_label,
            estimator=estimator, qpu_backend=qpu_backend,
        )
        results.append(result)

        elapsed_after = time.monotonic() - wall_start
        if elapsed_after >= max_qpu_seconds and i + 1 < len(molecules):
            remaining = molecules[i + 1:]
            detail = (
                f"Wall-clock cap ({max_qpu_seconds}s) exceeded after '{molecule}' "
                f"({elapsed_after:.1f}s elapsed) — aborting remaining molecules: "
                f"{', '.join(remaining)}"
            )
            _log.warning(detail)
            log_policy_event(event_type="run_deferred", status="deferred", detail=detail)
            break

    return results


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monthly VQE QPU benchmark runner."
    )
    parser.add_argument("--molecule", choices=["h2", "lih", "all"], default="all")
    parser.add_argument(
        "--backend", choices=["aer", "qpu"], default="aer",
        help="Evaluation backend (default: aer statevector). 'qpu' is budget-checked "
             "against the shared monthly free tier and falls back to aer if exhausted.",
    )
    parser.add_argument(
        "--max-qpu-seconds", type=int, default=MAX_QPU_SECONDS, metavar="SECONDS",
        help=f"Hard wall-clock cap in seconds (default: {MAX_QPU_SECONDS}).",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Log a run_started/skipped pair but do not execute VQE.")
    parser.add_argument("--defer-reason", type=str, default="",
                        help="Log a deferred event and exit without running the benchmark.")
    parser.add_argument("--manual-override-note", type=str, default="",
                        help="Optional note to log a manual override event before benchmark start.")
    parser.add_argument("--no-dashboard", action="store_true",
                        help="Skip auto-regeneration of the benchmark dashboard.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.defer_reason.strip():
        detail = f"Deferred benchmark run: {args.defer_reason.strip()}"
        log_policy_event(event_type="run_deferred", status="deferred", detail=detail)
        _log.info(detail)
        sys.exit(0)

    if args.manual_override_note.strip():
        detail = f"Manual override noted: {args.manual_override_note.strip()}"
        log_policy_event(event_type="manual_override", status="manual_override", detail=detail)

    import init_db
    conn = init_db.get_connection()
    _ensure_policy_events_table(conn)
    backend_choice, deferred_detail = resolve_backend_choice(
        args.backend, conn, required_seconds=args.max_qpu_seconds,
    )
    conn.close()
    if deferred_detail:
        _log.warning(deferred_detail)
        log_policy_event(event_type="run_deferred", status="deferred", detail=deferred_detail)

    backend_label = "aer_statevector" if backend_choice == "aer" else "ibm_qpu_estimator_v2"

    started_detail = (
        f"Started benchmark; schedule={execution_policy.schedule_label(POLICY_ID)}; "
        f"backend={backend_label}; qpu_cap={args.max_qpu_seconds}s"
    )
    log_policy_event(event_type="run_started", status="started", detail=started_detail)

    if args.dry_run:
        _log.info("DRY RUN — no VQE optimization executed, no DB write, no dashboard update.")
        log_policy_event(
            event_type="run_completed", status="skipped",
            detail="Dry-run executed; no VQE run and no persistence.",
        )
        sys.exit(0)

    molecules = ["h2", "lih"] if args.molecule == "all" else [args.molecule]

    try:
        results = run_all_molecules(
            molecules, backend_label=backend_label, max_qpu_seconds=args.max_qpu_seconds,
        )
    except Exception as exc:
        _log.error("Benchmark run failed: %s", exc)
        log_policy_event(
            event_type="run_completed", status="failed",
            detail=f"Benchmark execution failed: {exc}",
        )
        sys.exit(1)

    if not results:
        log_policy_event(
            event_type="run_completed", status="failed",
            detail="No molecules completed before the wall-clock cap was reached.",
        )
        sys.exit(1)

    all_met = all(r["ac_met"] for r in results)
    ran = ", ".join(r["molecule"] for r in results)

    if not args.no_dashboard:
        dash_script = _ROOT / "tools" / "gen_benchmark_dashboard.py"
        try:
            # --static is required: without it gen_benchmark_dashboard.py
            # starts a long-running local server and never returns, which
            # would block this script forever before it can log run_completed.
            subprocess.run(
                [sys.executable, str(dash_script), "--static", "--no-open"],
                check=True, cwd=str(_ROOT), timeout=120,
            )
            _log.info("Dashboard regenerated.")
        except Exception as exc:
            _log.warning("Dashboard regeneration failed: %s", exc)

    status = "succeeded" if all_met else "failed"
    status_detail = (
        f"Benchmark completed; molecules={ran}; backend={backend_label}; "
        f"all_ac_met={all_met}"
    )
    log_policy_event(event_type="run_completed", status=status, detail=status_detail)

    print(f"\n{'='*56}")
    print(f"  VQE benchmark complete: {'SUCCESS' if all_met else 'ACCURACY TARGET MISSED'}")
    print(f"  Molecules run: {ran}")
    print(f"  Backend: {backend_label}")
    print(f"{'='*56}\n")

    sys.exit(0 if all_met else 1)


if __name__ == "__main__":
    main()
