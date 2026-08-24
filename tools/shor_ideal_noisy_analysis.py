"""Deterministic analysis primitives for ideal and noisy Shor benchmarks."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import json
import importlib.metadata
from math import sqrt
from random import Random
from statistics import mean, variance
import argparse
import sys
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parent.parent
_SRC_UTILS = _ROOT / "src" / "utils"
if str(_SRC_UTILS) not in sys.path:
    sys.path.insert(0, str(_SRC_UTILS))


def wilson_interval(successes: int, repetitions: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Return a two-sided Wilson confidence interval for a binomial rate."""
    if repetitions <= 0 or successes < 0 or successes > repetitions:
        raise ValueError("successes must be between zero and repetitions")
    proportion = successes / repetitions
    denominator = 1 + z**2 / repetitions
    centre = (proportion + z**2 / (2 * repetitions)) / denominator
    margin = z * sqrt(
        proportion * (1 - proportion) / repetitions + z**2 / (4 * repetitions**2)
    ) / denominator
    return (centre - margin, centre + margin)


def analyze_trials(
    trials: Sequence[Mapping[str, Any]],
    *,
    mode: str,
    repetitions: int,
    seed: int | None,
    provenance: Mapping[str, str],
) -> dict[str, Any]:
    """Summarize factorization trials with success as the primary metric."""
    if mode not in {"ideal", "noisy", "qpu"}:
        raise ValueError("mode must be ideal, noisy, or qpu")
    if repetitions != len(trials) or repetitions <= 0:
        raise ValueError("repetitions must equal the non-empty trial count")

    successes = sum(bool(trial.get("success", False)) for trial in trials)
    orders = [int(trial["order"]) for trial in trials if trial.get("order") is not None]
    order_distribution = {str(order): count for order, count in sorted(Counter(orders).items())}
    order_summary: dict[str, Any] = {
        "count": len(orders),
        "mean": mean(orders) if orders else None,
        "variance": variance(orders) if len(orders) > 1 else 0.0 if orders else None,
        "distribution": order_distribution,
    }
    return {
        "mode": mode,
        "repetitions": repetitions,
        "seed": seed,
        "successes": successes,
        "success_rate": successes / repetitions,
        "success_rate_ci_95": wilson_interval(successes, repetitions),
        "order_summary": order_summary,
        "provenance": dict(provenance),
    }


def run_seeded_replay(
    *,
    repetitions: int = 100,
    seed: int = 0,
    sampler: Callable[[str, Random], Mapping[str, Any]],
    provenance: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """Run deterministic ideal and noisy trial streams through one sampler."""
    if repetitions <= 0:
        raise ValueError("repetitions must be positive")
    results: dict[str, dict[str, Any]] = {}
    for mode in ("ideal", "noisy"):
        random_source = Random(seed)
        trials = [sampler(mode, random_source) for _ in range(repetitions)]
        results[mode] = analyze_trials(
            trials,
            mode=mode,
            repetitions=repetitions,
            seed=seed,
            provenance=provenance,
        )
    return results


def persist_replay_results(results: Mapping[str, Mapping[str, Any]], *, n_value: int) -> None:
    """Persist one encrypted-database row for each offline benchmark mode."""
    import init_db

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    conn = init_db.get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS shor_replay_benchmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            mode TEXT NOT NULL CHECK(mode IN ('ideal', 'noisy', 'qpu')),
            n_value INTEGER NOT NULL,
            repetitions INTEGER NOT NULL,
            successes INTEGER NOT NULL,
            success_rate REAL NOT NULL,
            ci_95_low REAL NOT NULL,
            ci_95_high REAL NOT NULL,
            seed INTEGER,
            order_summary_json TEXT NOT NULL,
            provenance_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    for mode, result in results.items():
        low, high = result["success_rate_ci_95"]
        conn.execute(
            """INSERT INTO shor_replay_benchmarks
            (run_id, mode, n_value, repetitions, successes, success_rate,
             ci_95_low, ci_95_high, seed, order_summary_json, provenance_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                mode,
                n_value,
                result["repetitions"],
                result["successes"],
                result["success_rate"],
                low,
                high,
                result.get("seed"),
                json.dumps(result["order_summary"], sort_keys=True),
                json.dumps(result["provenance"], sort_keys=True),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    conn.commit()
    conn.close()


def _default_sampler(mode: str, random_source: Random) -> Mapping[str, Any]:
    """Execute one N=15 order-finding trial on local Qiskit Aer."""
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import NoiseModel, depolarizing_error

    import run_shors_bench

    circuit, _ = run_shors_bench._build_shor_circuit_n15(4)
    circuit = circuit.decompose(reps=5)
    noise_model = None
    if mode == "noisy":
        noise_model = NoiseModel()
        noise_model.add_all_qubit_quantum_error(depolarizing_error(0.005, 1), ["x", "h"])
        noise_model.add_all_qubit_quantum_error(depolarizing_error(0.02, 2), ["cx"])
        noise_model.add_all_qubit_quantum_error(depolarizing_error(0.02, 3), ["cswap"])
    backend = AerSimulator(noise_model=noise_model)
    counts = backend.run(
        circuit,
        shots=1,
        seed_simulator=random_source.randrange(2**32),
    ).result().get_counts()
    for phase in run_shors_bench._phase_from_counts(counts, 4):
        order = run_shors_bench._order_from_phase(phase, 15)
        if order is not None:
            factors = run_shors_bench._factors_from_order(7, order, 15)
            return {"success": factors is not None, "order": order}
    return {"success": False, "order": None}


def _default_provenance() -> dict[str, str]:
    """Return versions and calibration details for the local Aer run."""
    return {
        "provider": "qiskit-aer",
        "version": importlib.metadata.version("qiskit-aer"),
        "ideal_model": "AerSimulator exact/noiseless",
        "noisy_model": "fixed depolarizing error: 0.005 1q, 0.02 2q",
        "calibration": "synthetic fixed calibration; no QPU calibration data",
        "circuit": "N=15, a=7, n_count=4",
    }


def run_benchmark(
    *,
    repetitions: int = 100,
    seed: int = 0,
    n_value: int = 15,
    sampler: Callable[[str, Random], Mapping[str, Any]] | None = None,
    provenance: Mapping[str, str] | None = None,
    persist: bool = True,
) -> dict[str, dict[str, Any]]:
    """Run the offline ideal/noisy benchmark; never submits a QPU job."""
    if n_value != 15:
        raise ValueError("Only N=15 is supported by the local Shor circuit")
    selected_sampler = sampler or _default_sampler
    results = run_seeded_replay(
        repetitions=repetitions,
        seed=seed,
        sampler=selected_sampler,
        provenance=provenance or _default_provenance(),
    )
    if persist:
        persist_replay_results(results, n_value=n_value)
    return results


def main() -> None:
    """Run the offline benchmark from the command line."""
    parser = argparse.ArgumentParser(description="Run ideal versus noisy Shor analysis with Aer.")
    parser.add_argument("--repetitions", type=int, default=100)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n", type=int, default=15)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()
    results = run_benchmark(
        repetitions=args.repetitions,
        seed=args.seed,
        n_value=args.n,
        persist=not args.no_persist,
    )
    for mode, result in results.items():
        low, high = result["success_rate_ci_95"]
        print(
            f"{mode}: success={result['successes']}/{result['repetitions']} "
            f"rate={result['success_rate']:.3f} CI95=({low:.3f}, {high:.3f})"
        )


if __name__ == "__main__":
    main()