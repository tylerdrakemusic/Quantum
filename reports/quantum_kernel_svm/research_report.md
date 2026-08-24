# Quantum Kernel SVM Feasibility Prototype

## Scope

This is a local Qiskit Aer-only feasibility experiment over generated,
episode-level fixtures. It is not a clinical, diagnostic, treatment,
investment, production, quantum-advantage, or real-world performance claim.

## Frozen configuration

```json
{
  "backend": "qiskit-aer",
  "classical_comparator": "sklearn-rbf-svc",
  "fixture_seed": 7,
  "kernel": "statevector-fidelity",
  "raw_data_persisted": false,
  "row_level_outputs_persisted": false,
  "seed": 19,
  "test_size": 0.25
}
```

## Evidence summary

- Subjects: 12; episodes: 36.
- Holdout: grouped and stratified by subject; subject identifiers are stored only as truncated SHA-256 hashes.
- Class balance: {"test": {"0": 3, "1": 6}, "total": {"0": 18, "1": 18}, "train": {"0": 15, "1": 12}}.
- Quantum Kernel SVM metrics: {"accuracy": 1.0, "balanced_accuracy": 1.0, "f1": 1.0}.
- Classical RBF SVM metrics: {"accuracy": 1.0, "balanced_accuracy": 1.0, "f1": 1.0}.
- Aggregate evidence JSON: `quantum_kernel_svm_evidence.json`.

## Leakage and retention controls

The prototype rejects overlapping subject groups and episode identifiers
between train and test. Raw fixtures, row-level outputs, and model outputs
remain in memory only. Persisted evidence contains counts, configuration,
aggregate metrics, aggregate error counts, and non-reversible subject hashes.
No database schema or database reader is used.

## Limitations and next handoff

The fixture is deliberately small and synthetic, and the fidelity kernel uses
ideal Aer statevector simulation without hardware noise, calibration effects,
or external validation. Kernel computation is intentionally simple and is not
evidence of quantum advantage. A follow-up may compare additional synthetic
distributions and noise models, subject to the same retention and scope gates.
