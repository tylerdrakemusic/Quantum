"""
⟨ψ⟩Quantum — tools/fill_cache.py

Band-aware IBM Quantum bitstring cache filler.

Submits H-gate measurement circuits to IBM Quantum (free tier: 10 QPU-min/month)
and writes results to the ty_string_cache. Caps QPU execution time at
MAX_QPU_SECONDS to preserve remaining monthly quota for algorithm experiments.

Usage
-----
    # Scheduled (monthly, 1st of month 2AM via QuantumCacheFill_Monthly task):
    C:\\G\\python.exe tools\\fill_cache.py

    # Interactive / ad-hoc:
    C:\\G\\python.exe tools\\fill_cache.py --max-qpu-seconds 180 --dry-run

    # Check remaining bits in cache without running:
    C:\\G\\python.exe tools\\fill_cache.py --status

Output
------
    f:\\⟨ψ⟩Quantum\\qbackups\\ty_string_cache_<YYYYMMDD_HHMMSS>.txt  (timestamped backup)
    f:\\⟨ψ⟩Quantum\\src\\data\\qbackups\\ty_string_cache.txt           (live, latest)

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
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent   # f:\⟨ψ⟩Quantum\
_BACKUP_DIR = _ROOT / "qbackups"
_LIVE_DIR   = _ROOT / "src" / "data" / "qbackups"
_LIVE_CACHE = _LIVE_DIR / "ty_string_cache.txt"

# ---------------------------------------------------------------------------
# Constants — tune these to control IBM quota usage
# ---------------------------------------------------------------------------

# Total QPU execution time to consume before stopping gracefully.
# 3 minutes leaves 7 minutes for algorithm experiments.
DEFAULT_MAX_QPU_SECONDS: int = 180   # 3 minutes

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

    # ----- Job loop -----
    all_bitstrings: list[str] = []
    jobs_submitted = 0
    jobs_completed = 0
    qpu_seconds_consumed = 0.0

    sampler = Sampler(backend)

    while qpu_seconds_consumed < max_qpu_seconds:
        remaining = max_qpu_seconds - qpu_seconds_consumed
        _logger.info(
            "Submitting job %d  (QPU used: %.1fs / %ds, remaining: %.1fs)",
            jobs_submitted + 1, qpu_seconds_consumed, max_qpu_seconds, remaining,
        )

        try:
            job = sampler.run([transpiled], shots=N_SHOTS)
            jobs_submitted += 1

            # Poll for completion
            poll_start = time.monotonic()
            result = job.result()
            wall_elapsed = time.monotonic() - poll_start

            # Extract QPU execution time from result metadata if available
            try:
                usage = result.metadata.get("execution", {})
                qpu_elapsed = float(usage.get("execution_spans_seconds", wall_elapsed))
            except (AttributeError, TypeError, ValueError):
                qpu_elapsed = wall_elapsed

            qpu_seconds_consumed += qpu_elapsed
            jobs_completed += 1

            # Extract bitstrings from SamplerV2 result.
            # Classical register is named after the creg in the circuit.
            # QuantumCircuit(n, n) names it 'c0'; named circuits may differ.
            pub_result = result[0]
            data = pub_result.data
            # Get the first BitArray attribute, whatever it's named
            creg_name = next(iter(vars(data)))
            counts = getattr(data, creg_name).get_counts()  # type: ignore[attr-defined]
            bitstrings = _counts_to_bitstrings(counts)
            all_bitstrings.extend(bitstrings)

            _logger.info(
                "Job %d done — %.1fs QPU, %d bitstrings, total bits so far: %d",
                jobs_completed, qpu_elapsed, len(bitstrings),
                sum(len(b) for b in all_bitstrings),
            )

        except Exception as exc:  # noqa: BLE001
            _logger.warning("Job %d failed: %s — stopping.", jobs_submitted, exc)
            break

    # ----- Write output -----
    total_bits = sum(len(b) for b in all_bitstrings)
    _logger.info("=== Fill complete ===")
    _logger.info("Jobs submitted : %d", jobs_submitted)
    _logger.info("Jobs completed : %d", jobs_completed)
    _logger.info("QPU time used  : %.1f s", qpu_seconds_consumed)
    _logger.info("Total bits     : %d", total_bits)

    if total_bits == 0:
        _logger.warning("No bits collected — cache not updated.")
        return 0

    # Ensure output directories exist
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    _LIVE_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = _BACKUP_DIR / f"ty_string_cache_{timestamp}.txt"

    with open(backup_path, "w", encoding="utf-8") as fh:
        for line in all_bitstrings:
            fh.write(line + "\n")

    shutil.copy2(backup_path, _LIVE_CACHE)

    _logger.info("Backup written : %s  (%d bytes)", backup_path, backup_path.stat().st_size)
    _logger.info("Live cache     : %s", _LIVE_CACHE)

    return total_bits


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

    if args.status:
        _print_status()
        sys.exit(0)

    try:
        bits = run_fill(
            max_qpu_seconds=args.max_qpu_seconds,
            dry_run=args.dry_run,
        )
        if bits > 0:
            _logger.info("Cache fill successful. Run with --status to verify.")
        sys.exit(0)
    except KeyboardInterrupt:
        _logger.info("Interrupted by user — partial results discarded.")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        _logger.error("fill_cache.py failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
