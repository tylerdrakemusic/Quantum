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
    try:
        baseline = load_regression_baseline()
        seed = int(baseline["seed"] if args.seed is None else args.seed)
        results = run_validation_matrix(seed=seed)
        validation = validate_regression_baseline(results, baseline)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(
            json.dumps(
                {"validation": {"status": "fail", "error": str(exc)}},
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    payload = {
        "validation": validation,
        "seed": seed,
        "cases": len(results),
        "decoder_successes": sum(1 for result in results if result["decoder_success"]),
        "logical_errors": sum(1 for result in results if result["logical_error"]),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if validation.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())