"""Run the local synthetic Quantum Kernel SVM feasibility experiment."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from quantum_kernel_svm import (  # noqa: E402
    build_synthetic_episodes,
    run_feasibility_prototype,
    validate_approval_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-seed", type=int, default=7)
    parser.add_argument("--split-seed", type=int, default=19)
    parser.add_argument("--subjects", type=int, default=12)
    parser.add_argument("--episodes-per-subject", type=int, default=3)
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--approval-manifest", type=Path)
    parser.add_argument("--approve", action="store_true", dest="cli_approved")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "reports" / "quantum_kernel_svm")
    args = parser.parse_args()

    if not args.synthetic_only or args.approval_manifest is None or not args.cli_approved:
        parser.error("--synthetic-only, --approval-manifest, and --approve are required")
    try:
        manifest_data = json.loads(args.approval_manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest_data, dict):
            raise ValueError("approval manifest must be a JSON object")
        validate_approval_manifest(
            manifest_data,
            cli_approved=args.cli_approved,
            synthetic_only=args.synthetic_only,
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(f"approval denied: {error}")

    episodes = build_synthetic_episodes(args.fixture_seed, args.subjects, args.episodes_per_subject)
    result = run_feasibility_prototype(episodes, seed=args.split_seed)
    result.aggregate_json["config"]["fixture_seed"] = args.fixture_seed
    evidence_path = result.write_evidence(args.output_dir)
    report_path = args.output_dir / "research_report.md"
    quantum = result.aggregate_json["metrics"]["quantum_kernel_svm"]
    classical = result.aggregate_json["metrics"]["classical_rbf_svm"]
    report = f"""# Quantum Kernel SVM Feasibility Prototype

## Scope

This is a local Qiskit Aer-only feasibility experiment over generated,
episode-level fixtures. It is not a clinical, diagnostic, treatment,
investment, production, quantum-advantage, or real-world performance claim.

## Frozen configuration

```json
{json.dumps(result.aggregate_json["config"], indent=2, sort_keys=True)}
```

## Evidence summary

- Subjects: {result.aggregate_json["counts"]["subjects"]}; episodes: {result.aggregate_json["counts"]["episodes"]}.
- Holdout: grouped and stratified by subject; persisted identifiers are full salted digests that are not linkable or reversible.
- Class balance: {json.dumps(result.aggregate_json["class_balance"], sort_keys=True)}.
- Quantum Kernel SVM metrics: {json.dumps(quantum, sort_keys=True)}.
- Classical RBF SVM metrics: {json.dumps(classical, sort_keys=True)}.
- Aggregate evidence JSON: `quantum_kernel_svm_evidence.json`.

## Leakage and retention controls

The prototype rejects overlapping subject groups and episode identifiers
between train and test. Raw fixtures, row-level outputs, and model outputs
remain in memory only. Persisted evidence contains counts, configuration,
aggregate metrics, aggregate error counts, and per-run salted subject digests.
The random salt exists only in memory, so the digests are not linkable across
runs or reversible into subject identifiers. No database schema or database
reader is used.

## Limitations and next handoff

The fixture is deliberately small and synthetic, and the fidelity kernel uses
ideal Aer statevector simulation without hardware noise, calibration effects,
or external validation. Kernel computation is intentionally simple and is not
evidence of quantum advantage. A follow-up may compare additional synthetic
distributions and noise models, subject to the same retention and scope gates.
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(json.dumps({"evidence": str(evidence_path), "report": str(report_path), "metrics": result.aggregate_json["metrics"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())