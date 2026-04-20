#!/usr/bin/env python3
"""
Shor's Algorithm v2 — Benchmark Runner

Benchmark Plan
--------------
Target:   N = 15 (the only N with proper modular exponentiation in shors_v2.py)
Backend:  IBM Quantum (champion) → Aer simulator (fallback)
Qubits:   8 counting + 4 problem = 12 total
Metrics:  Wall-clock time, order found, factors, backend name, local timestamp
Output:   Inserts row into quantumpsi.db benchmarks table (SQLCipher encrypted)

Existing benchmark rows (from v1/earlier runs) used N ∈ {299, 323, 361, 377}
on 27-qubit IBM hardware. Those used a different circuit construction.
The v2 code only implements c_amodN for N=15, so that's what we benchmark here.

Usage:
  python tools/bench_shors_v2.py [--backend sim|ibm|auto] [--n-count 8]
"""

import sys
import time
from datetime import datetime
import argparse
from pathlib import Path
from math import gcd, ceil, log2

# Ensure project src is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src" / "core"))

from quantum_rt import qRax
from quantum_backend import QuantumBackendManager, ProviderTier

# Import shors_v2 components
sys.path.insert(0, str(PROJECT_ROOT / "research"))
from shors_v2 import ShorsAlgorithm

# Import DB connection
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from utils.init_db import get_connection, init_db


def _get_backend_label(backend, provider: ProviderTier) -> str:
    """Return a human-readable backend label for the DB row."""
    if provider == ProviderTier.AER_SIMULATOR:
        return "aer_simulator"
    return getattr(backend, 'name', str(backend))


def get_random_coprime(N: int) -> int:
    """Pick a random integer a where 1 < a < N and gcd(a, N) == 1."""
    while True:
        a = int(qRax(2, N - 1))
        if gcd(a, N) == 1:
            return a


def run_benchmark(backend_choice: str = "auto", n_count: int = 8) -> dict:
    """Run one Shor's v2 benchmark on N=15 and return results dict."""
    # N is now passed as an argument
    max_attempts = 5
    required_qubits = n_count + int(ceil(log2(N)))  # 8 + 4 = 12

    print("=" * 60)
    print(f"  SHOR'S v2 BENCHMARK")
    print(f"  N = {N}  |  n_count = {n_count}  |  qubits = {required_qubits}")
    print(f"  Backend: {backend_choice}  |  Max attempts: {max_attempts}")
    print(f"  Output: quantumpsi.db → benchmarks")
    print("=" * 60)

    # Select backend
    mgr = QuantumBackendManager()
    if backend_choice == "sim":
        backend = mgr.get_aer_backend(required_qubits)
        provider = ProviderTier.AER_SIMULATOR
    elif backend_choice == "ibm":
        backend, provider = mgr.get_backend(required_qubits, require_real_hw=True)
    else:  # auto
        backend, provider = mgr.get_backend(required_qubits)

    if backend is None:
        print("ERROR: No backend available.")
        return {"success": False, "error": "no_backend"}

    backend_label = _get_backend_label(backend, provider)
    print(f"  Using: {backend_label} ({provider.value})")
    print("-" * 60)

    # Capture local timestamp at benchmark start (to the second)
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    start_time = time.time()
    factor1, factor2, order_r = None, None, -1
    found = False

    for attempt in range(1, max_attempts + 1):
        a = get_random_coprime(N)
        print(f"  Attempt {attempt}/{max_attempts}: a = {a}")

        shor = ShorsAlgorithm(a=a, N=N, n_count=n_count)
        order_r = shor.run(backend)

        if order_r != -1:
            print(f"    Order r = {order_r}")
            if order_r % 2 == 0:
                x = pow(a, order_r // 2, N)
                if x != 1 and x != N - 1:
                    f1 = gcd(x - 1, N)
                    f2 = gcd(x + 1, N)
                    if f1 not in (1, N) and f2 not in (1, N):
                        factor1, factor2 = f1, f2
                        print(f"    Factors: {factor1} x {factor2} = {N}")
                        found = True
                        break
                    else:
                        print(f"    Trivial factors ({f1}, {f2}), retrying...")
                else:
                    print(f"    x = {x} (±1 mod N), retrying...")
            else:
                print(f"    Odd order, retrying...")
        else:
            print(f"    No valid order found, retrying...")

    total_time = time.time() - start_time

    # Insert into encrypted DB
    init_db()
    conn = get_connection()
    conn.execute(
        "INSERT INTO benchmarks (algorithm, total_time_sec, required_qubits, n_value, order_r, factor1, factor2, backend, timestamp) VALUES (?,?,?,?,?,?,?,?,?)",
        ("shors_v2", round(total_time, 3), required_qubits, N, order_r, factor1, factor2, backend_label, ts),
    )
    conn.commit()
    conn.close()
    print(f"  Row inserted into quantumpsi.db benchmarks table")

    # Auto-regenerate dashboard after each run
    try:
        import subprocess
        dashboard_path = str(PROJECT_ROOT / "tools" / "bench_dashboard.py")
        subprocess.run([sys.executable, dashboard_path, "--no-open"], check=True)
        print("  Dashboard auto-regenerated.")
    except Exception as e:
        print(f"  [WARN] Could not auto-regenerate dashboard: {e}")

    # Print summary
    print("-" * 60)
    status = "SUCCESS" if found else "FAILED"
    print(f"  Result:    {status}")
    print(f"  Time:      {total_time:.3f}s")
    print(f"  Qubits:    {required_qubits}")
    print(f"  Order:     {order_r}")
    if found:
        print(f"  Factors:   {factor1} x {factor2}")
    print(f"  Backend:   {backend_label}")
    print(f"  Timestamp: {ts}")
    print("=" * 60)

    return {
        "success": found,
        "total_time_sec": total_time,
        "required_qubits": required_qubits,
        "N": N,
        "order_r": order_r,
        "factor1": factor1,
        "factor2": factor2,
        "backend": backend_label,
        "timestamp": ts,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Shor's v2 benchmark runner")
    parser.add_argument("--backend", choices=["auto", "sim", "ibm"], default="auto",
                        help="Backend selection: auto (IBM→sim fallback), sim, ibm")
    parser.add_argument("--n-count", type=int, default=8,
                        help="Number of counting qubits (default: 8)")
    parser.add_argument("--N", type=int, default=15,
                        help="Composite number to factor (default: 15)")
    args = parser.parse_args()

    # Pass N to run_benchmark
    global N
    N = args.N
    run_benchmark(backend_choice=args.backend, n_count=args.n_count)
