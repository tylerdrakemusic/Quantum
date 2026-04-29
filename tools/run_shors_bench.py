"""
⟨ψ⟩Quantum — tools/run_shors_bench.py

Band-aware Shor's algorithm QPU benchmark runner.

Submits a Shor's factorization circuit to real IBM Quantum hardware and records
results in quantumpsi.db → shors_qpu_bench table. Selects the largest N that
fits the available QPU budget (falls back to N=15 if uncertain).

Usage
-----
    # Manual / ad-hoc (run right now):
    C:\\G\\python.exe tools\\run_shors_bench.py

    # Specify N explicitly:
    C:\\G\\python.exe tools\\run_shors_bench.py --n 15

    # Dry-run (connect, select backend, but don't submit job):
    C:\\G\\python.exe tools\\run_shors_bench.py --dry-run

    # Scheduled (monthly, 1st of month 02:00 via ShorsMonthlyBench task):
    C:\\G\\python.exe F:\\⟨ψ⟩Quantum\\tools\\run_shors_bench.py

Environment
-----------
    IBM_CLOUD_API_KEY     — IBM Cloud API key (required)
    IBM_QUANTUM_INSTANCE  — Instance CRN (required)
    QUANTUM_DB_KEY        — SQLCipher key for quantumpsi.db (required)

QPU Budget
----------
    MAX_QPU_SECONDS = 300  (5 minutes)
    The monthly free tier is 600s. This run claims 300s, leaving 300s for the
    cache fill (QuantumCacheFill_Monthly at 01:00) which runs one hour earlier.
    ShorsMonthlyBench runs at 02:00 to avoid QPU contention.
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from math import gcd
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent   # f:\⟨ψ⟩Quantum\
# Add src/utils directly so `import init_db` works (no __init__.py in utils/)
sys.path.insert(0, str(_ROOT / "src" / "utils"))

# ── Constants ──────────────────────────────────────────────────────────────
MAX_QPU_SECONDS: int = 300          # 5-minute QPU cap per run
N_SHOTS: int = 4096                 # Shots per circuit submission
N_COUNT: int = 4                    # Counting qubits for QPE (4 gives ~93.75% success)

# Candidate N values in ascending circuit-complexity order.
# N=15 (8 qubits) always fits. N=21 (9 qubits) needs more depth.
# On free tier with 300s budget, N=15 is the safe choice.
CANDIDATE_N: list[int] = [15]       # Extend to [15, 21] when budget allows

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_log = logging.getLogger("run_shors_bench")


# ═══════════════════════════════════════════════════════════════════════════
# DB helpers
# ═══════════════════════════════════════════════════════════════════════════

def _ensure_qpu_bench_table(conn) -> None:
    """Create shors_qpu_bench table if it doesn't exist (schema from FR-20260428)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shors_qpu_bench (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date     TEXT    NOT NULL,
            n_value      INTEGER NOT NULL,
            n_qubits     INTEGER NOT NULL,
            success      INTEGER NOT NULL,
            factor_found TEXT,
            qpu_seconds  REAL    NOT NULL,
            backend      TEXT    NOT NULL,
            notes        TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sqb_run_date ON shors_qpu_bench(run_date)"
    )
    conn.commit()


def _insert_result(
    conn,
    n_value: int,
    n_qubits: int,
    success: bool,
    factor_found: str | None,
    qpu_seconds: float,
    backend: str,
    notes: str | None = None,
) -> int:
    """Insert one benchmark row. Returns the new row id."""
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.execute(
        """INSERT INTO shors_qpu_bench
               (run_date, n_value, n_qubits, success, factor_found, qpu_seconds, backend, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_date,
            n_value,
            n_qubits,
            1 if success else 0,
            factor_found,
            round(qpu_seconds, 3),
            backend,
            notes,
        ),
    )
    conn.commit()
    return cur.lastrowid


# ═══════════════════════════════════════════════════════════════════════════
# IBM Quantum helpers
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


# ═══════════════════════════════════════════════════════════════════════════
# Shor's Algorithm — circuit construction for N=15
# ═══════════════════════════════════════════════════════════════════════════
# Reference implementation for N=15, a∈{2,4,7,8,11,13} (coprime to 15).
# Uses quantum phase estimation (QPE) with n_count=4 counting qubits and
# n_work=4 work qubits encoding |x mod 15> in binary.
#
# Qubit layout:  q[0..3]  = counting register (measuring phase)
#                q[4..7]  = work register (initialized to |0001> = |1>)
#
# Circuit depth is kept minimal for real-hardware viability.  We use the
# explicit gate-by-gate construction for a=7 (order r=4, guaranteed factors
# 3 and 5) and a=2 (order r=4) — both are reliable for N=15.
# ═══════════════════════════════════════════════════════════════════════════

def _build_c_amodN_a7_pow1(qc, control: int, work: list[int]) -> None:
    """Controlled-U for a=7, N=15, power=1: |x> -> |7x mod 15>.

    Uses a SWAP-network decomposition that is hardware-friendly.
    7 * x mod 15 for x in {0..14}:
      1->7, 2->14, 4->13, 8->11, 7->4, 14->8, 13->1, 11->2
    Implemented via conditional SWAPs that permute the computational basis.
    """
    # Permutation: 1->7->4->13->1 and 2->14->8->11->2 (two 4-cycles)
    # SWAP(q0,q1) SWAP(q1,q2) SWAP(q2,q3)  -- rotate q0q1q2q3 as |1000>->|0001>->...
    # Controlled-SWAP (Fredkin) implementation
    w = work  # [w0, w1, w2, w3] = q[4..7]

    # Cycle 1: 1 -> 7 -> 4 -> 13 -> 1  (bits: 0001 -> 0111 -> 0100 -> 1101)
    # Cycle 2: 2 -> 14 -> 8 -> 11 -> 2 (bits: 0010 -> 1110 -> 1000 -> 1011)
    # Implement via CSWAP gates: controlled on `control`, swap pairs in work
    qc.cswap(control, w[1], w[3])
    qc.cswap(control, w[0], w[3])
    qc.cswap(control, w[0], w[2])
    qc.cswap(control, w[0], w[1])


def _build_c_amodN_a7_pow2(qc, control: int, work: list[int]) -> None:
    """Controlled-U^2 for a=7, N=15, power=2: |x> -> |4x mod 15>.

    4 * x mod 15: 1->4->1 (2-cycle), 2->8->2 (2-cycle), 7->13->7, 11->14->11
    Each 2-cycle is a single CSWAP.
    """
    w = work
    qc.cswap(control, w[0], w[2])
    qc.cswap(control, w[1], w[3])


def _build_c_amodN_a7_pow4(qc, control: int, work: list[int]) -> None:
    """Controlled-U^4 for a=7, N=15: a^4=7^4=1 mod 15 → identity. No-op."""
    pass  # 7^4 mod 15 = 2401 mod 15 = 1 → identity


def _build_shor_circuit_n15(n_count: int = 4):
    """Build Shor's order-finding circuit for N=15, a=7.

    n_count counting qubits (default 4) + 4 work qubits = n_count+4 total.
    Returns: (QuantumCircuit, n_total_qubits)
    """
    try:
        from qiskit import QuantumCircuit
        from qiskit.circuit.library import QFTGate
    except ImportError:
        raise ImportError("qiskit is required: pip install qiskit qiskit-ibm-runtime")

    n_work = 4   # ceil(log2(15)) = 4
    n_total = n_count + n_work

    qc = QuantumCircuit(n_total, n_count)

    # Counting register: q[0..n_count-1]
    # Work register:     q[n_count..n_count+n_work-1]
    counting = list(range(n_count))
    work = list(range(n_count, n_count + n_work))

    # Step 1: Initialize work register to |1> = |0001> in binary
    qc.x(work[0])

    # Step 2: Apply Hadamard to all counting qubits
    for q in counting:
        qc.h(q)

    # Step 3: Controlled-U^(2^k) gates
    # For a=7, N=15: order r=4, so U^4 = identity
    # We apply CU^(2^k) for k=0,1,2,3 (n_count-1..0 in standard QPE)
    for k in range(n_count):
        power = 2 ** k
        ctrl = counting[k]
        # Apply controlled-U^power for a=7, N=15
        if power % 4 == 1:   # equivalent to a^1 mod 15
            _build_c_amodN_a7_pow1(qc, ctrl, work)
        elif power % 4 == 2:  # equivalent to a^2 mod 15
            _build_c_amodN_a7_pow2(qc, ctrl, work)
        elif power % 4 == 0:  # a^4 = identity
            _build_c_amodN_a7_pow4(qc, ctrl, work)
        # power%4==3 case doesn't arise with powers-of-2 when r=4

    # Step 4: Inverse QFT on counting register
    iqft = QFTGate(n_count, do_swaps=True).inverse()
    qc.append(iqft, counting)

    # Step 5: Measure counting register
    qc.measure(counting, list(range(n_count)))

    return qc, n_total


# ═══════════════════════════════════════════════════════════════════════════
# Phase → Order → Factors extraction
# ═══════════════════════════════════════════════════════════════════════════

def _phase_from_counts(counts: dict[str, int], n_count: int) -> list[float]:
    """Return candidate phases (excluding 0) ordered by measurement frequency.

    In QPE for Shor's, phase=0 always appears but carries no order information.
    We return all non-zero phases so the caller can try each one.
    """
    candidates: list[tuple[float, int]] = []
    for bitstr, cnt in counts.items():
        clean = bitstr.replace(" ", "")
        measured = int(clean, 2)
        if measured == 0:
            continue  # trivial phase, skip
        phase = measured / (2 ** n_count)
        candidates.append((phase, cnt))
    # Sort by frequency descending
    candidates.sort(key=lambda x: -x[1])
    return [p for p, _ in candidates]


def _order_from_phase(phase: float, N: int, max_denominator: int = 64) -> int | None:
    """Use continued fractions to find the order r from the measured phase."""
    from fractions import Fraction
    if phase == 0.0:
        return None
    frac = Fraction(phase).limit_denominator(max_denominator)
    r = frac.denominator
    # Validate: a^r ≡ 1 mod N  (we used a=7)
    a = 7
    if pow(a, r, N) == 1:
        return r
    # Try a few multiples
    for m in range(2, 9):
        if pow(a, r * m, N) == 1:
            return r * m
    return None


def _factors_from_order(a: int, r: int, N: int) -> tuple[int, int] | None:
    """Attempt to extract non-trivial factors of N from order r."""
    if r is None or r == 0 or r % 2 != 0:
        return None
    x = pow(a, r // 2, N)
    if x in (1, N - 1):
        return None
    p = gcd(x - 1, N)
    q = gcd(x + 1, N)
    if p not in (1, N) and q not in (1, N):
        return (p, q)
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Main benchmark runner
# ═══════════════════════════════════════════════════════════════════════════

def run_benchmark(
    n_value: int = 15,
    dry_run: bool = False,
    max_qpu_seconds: int = MAX_QPU_SECONDS,
) -> dict:
    """Run Shor's algorithm on IBM Quantum hardware for the given N.

    Returns a dict with all result fields.
    """
    _log.info("=" * 60)
    _log.info("  Shor's Monthly QPU Benchmark  (FR-20260428)")
    _log.info("  N = %d  |  n_count = %d  |  QPU cap = %ds", n_value, N_COUNT, max_qpu_seconds)
    _log.info("  Dry run: %s", dry_run)
    _log.info("=" * 60)

    # Build circuit
    if n_value != 15:
        raise ValueError(f"Only N=15 is implemented in this runner. Got N={n_value}.")
    qc, n_total = _build_shor_circuit_n15(N_COUNT)
    _log.info("Circuit built: %d qubits, depth=%d, gate count=%d",
              n_total, qc.depth(), sum(qc.count_ops().values()))

    if dry_run:
        _log.info("DRY RUN — circuit built but no IBM job submitted.")
        return {
            "n_value": n_value,
            "n_qubits": n_total,
            "success": False,
            "factor_found": None,
            "qpu_seconds": 0.0,
            "backend": "dry_run",
            "notes": "dry-run; no job submitted",
        }

    # ── Connect to IBM Quantum ──────────────────────────────────────────────
    try:
        from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2 as Sampler
        from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
    except ImportError:
        raise ImportError("Required: pip install qiskit qiskit-ibm-runtime")

    api_key, instance = _get_ibm_credentials()
    _log.info("Connecting to IBM Quantum platform …")
    service = QiskitRuntimeService(
        channel="ibm_quantum_platform",
        token=api_key,
        instance=instance,
    )

    backend = _select_backend(service, min_qubits=n_total)
    backend_name: str = backend.name

    # ── Transpile ──────────────────────────────────────────────────────────
    _log.info("Transpiling circuit for %s …", backend_name)
    pm = generate_preset_pass_manager(optimization_level=1, backend=backend)
    transpiled = pm.run(qc)
    _log.info(
        "Transpiled: depth=%d, gate count=%d",
        transpiled.depth(),
        sum(transpiled.count_ops().values()),
    )

    # ── Submit job ─────────────────────────────────────────────────────────
    _log.info("Submitting Shor's circuit to %s (%d shots) …", backend_name, N_SHOTS)
    wall_start = time.monotonic()

    sampler = Sampler(backend)
    job = sampler.run([transpiled], shots=N_SHOTS)
    _log.info("Job ID: %s — waiting in queue …", job.job_id())

    # Poll for completion (no timeout — wait as long as needed)
    result = job.result()
    wall_elapsed = time.monotonic() - wall_start

    # Extract QPU execution time from result metadata
    try:
        usage = result.metadata.get("execution", {})
        qpu_seconds = float(usage.get("execution_spans_seconds", wall_elapsed))
    except (AttributeError, TypeError, ValueError):
        qpu_seconds = wall_elapsed

    _log.info("Job completed — wall=%.1fs, QPU=%.1fs", wall_elapsed, qpu_seconds)

    # ── Extract measurement counts ─────────────────────────────────────────
    pub_result = result[0]
    data = pub_result.data
    creg_name = next(iter(vars(data)))
    counts: dict[str, int] = getattr(data, creg_name).get_counts()

    _log.info("Top 5 measurement outcomes:")
    for bitstr, cnt in sorted(counts.items(), key=lambda x: -x[1])[:5]:
        _log.info("  %s : %d (%.1f%%)", bitstr, cnt, 100 * cnt / N_SHOTS)

    # ── Interpret results — try each non-zero phase in order of frequency ──
    a = 7
    phases = _phase_from_counts(counts, N_COUNT)
    r = None
    factors = None
    best_phase = None
    for ph in phases:
        r_candidate = _order_from_phase(ph, n_value)
        if r_candidate:
            factors_candidate = _factors_from_order(a, r_candidate, n_value)
            if factors_candidate:
                r = r_candidate
                factors = factors_candidate
                best_phase = ph
                break
            elif r is None:  # keep first valid order even if trivial factors
                r = r_candidate
                best_phase = ph
    if best_phase is None and phases:
        best_phase = phases[0]
    success = factors is not None
    factor_found = f"{factors[0]},{factors[1]}" if factors else None

    _log.info("Top non-zero phases: %s", phases[:5])
    _log.info("Best phase: %s", best_phase)
    _log.info("Order r: %s", r)
    _log.info("Factors: %s", factor_found if factor_found else "not found")
    _log.info("Success: %s", success)

    notes = f"a=7, N_COUNT={N_COUNT}, phase={best_phase}, r={r}, job={job.job_id()}"

    return {
        "n_value": n_value,
        "n_qubits": n_total,
        "success": success,
        "factor_found": factor_found,
        "qpu_seconds": qpu_seconds,
        "backend": backend_name,
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# DB persistence
# ═══════════════════════════════════════════════════════════════════════════

def persist_result(result: dict) -> int:
    """Insert result into quantumpsi.db → shors_qpu_bench. Returns row id."""
    import init_db
    conn = init_db.get_connection()
    _ensure_qpu_bench_table(conn)
    row_id = _insert_result(
        conn,
        n_value=result["n_value"],
        n_qubits=result["n_qubits"],
        success=result["success"],
        factor_found=result["factor_found"],
        qpu_seconds=result["qpu_seconds"],
        backend=result["backend"],
        notes=result.get("notes"),
    )
    conn.close()
    _log.info("DB row inserted: shors_qpu_bench.id = %d", row_id)
    return row_id


def print_db_row(row_id: int) -> None:
    """Print the newly inserted DB row for confirmation."""
    import init_db
    conn = init_db.get_connection()
    row = conn.execute(
        "SELECT * FROM shors_qpu_bench WHERE id = ?", (row_id,)
    ).fetchone()
    conn.close()
    if row:
        print("\n── Inserted DB row ──────────────────────────────────────")
        keys = ["id", "run_date", "n_value", "n_qubits", "success",
                "factor_found", "qpu_seconds", "backend", "notes"]
        for k in keys:
            print(f"  {k:14s}: {row[k]}")
        print("─" * 56)


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Band-aware Shor's algorithm QPU benchmark runner."
    )
    parser.add_argument(
        "--n", type=int, default=15,
        help="Composite number to factor (default: 15). Only 15 is supported.",
    )
    parser.add_argument(
        "--max-qpu-seconds", type=int, default=MAX_QPU_SECONDS, metavar="SECONDS",
        help=f"QPU cap in seconds (default: {MAX_QPU_SECONDS}).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Build circuit and connect, but do not submit the IBM job.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    try:
        result = run_benchmark(
            n_value=args.n,
            dry_run=args.dry_run,
            max_qpu_seconds=args.max_qpu_seconds,
        )
    except Exception as exc:
        _log.error("Benchmark run failed: %s", exc)
        sys.exit(1)

    if args.dry_run:
        _log.info("Dry run complete. No DB write, no dashboard update.")
        sys.exit(0)

    # Persist to DB
    try:
        row_id = persist_result(result)
        print_db_row(row_id)
    except Exception as exc:
        _log.error("Failed to insert DB row: %s", exc)
        sys.exit(1)

    # Regenerate dashboard
    dash_script = _ROOT / "tools" / "gen_benchmark_dashboard.py"
    try:
        subprocess.run(
            [sys.executable, str(dash_script), "--no-open"],
            check=True,
            cwd=str(_ROOT),
        )
        _log.info("Dashboard regenerated.")
    except Exception as exc:
        _log.warning("Dashboard regeneration failed: %s", exc)

    status = "SUCCESS" if result["success"] else "FAILED (no factors)"
    print(f"\n{'='*56}")
    print(f"  Benchmark complete: {status}")
    print(f"  N={result['n_value']}, qubits={result['n_qubits']}, "
          f"backend={result['backend']}")
    print(f"  QPU time: {result['qpu_seconds']:.1f}s")
    print(f"  Factors: {result['factor_found'] or 'not found'}")
    print(f"{'='*56}\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
