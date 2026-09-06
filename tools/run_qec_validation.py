"""Run the fixed local QEC validation matrix and check its baseline."""
from __future__ import annotations

import argparse
import json

from quantum_toolkit.qec_validation import (
    load_regression_baseline,
    run_validation_matrix,
    validate_regression_baseline,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    baseline = load_regression_baseline()
    seed = int(baseline["seed"] if args.seed is None else args.seed)
    results = run_validation_matrix(seed=seed)
    validation = validate_regression_baseline(results, baseline)
    print(
        json.dumps(
            {
                "validation": validation,
                "seed": seed,
                "cases": len(results),
                "decoder_successes": sum(bool(result["decoder_success"]) for result in results),
                "logical_errors": sum(bool(result["logical_error"]) for result in results),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())