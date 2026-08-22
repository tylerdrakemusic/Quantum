# Aer Noise-Model Library

`utils.aer_noise_model.build_noise_model` constructs a local Qiskit Aer
`NoiseModel` from a versioned IBM backend-properties calibration snapshot.
The builder has no IBM Runtime or live-QPU dependency.

## Snapshot contract

Snapshots retain `backend_name`, `provider`, `source`,
`last_update_date`, `retrieved_at`, qubit calibration values, and gate
calibration values. The checked-in test fixture demonstrates the supported
shape in `tests/fixtures/ibm_fez_2026-08-22.json`.

## Result states

The result always includes metadata with the calibration timestamp, source
identifiers, model version, seed, supported mappings, proxy mappings,
unsupported fields, and warnings. Only `ready` returns a model. `missing`,
`undated`, `aging`, `stale`, and `unmappable` return no model, so incomplete,
old, or unsupported data cannot appear authoritative.

The model is an **Aer with an IBM-derived approximate noise model**. Gate
errors map to depolarizing errors, readout errors map to readout errors, and
available `T1`/`T2` values contribute thermal relaxation for one-qubit gates.
Cross-talk, drift, pulse schedules, and other live control-stack behavior are
explicitly unsupported. This library does not alter benchmark defaults,
execution policy, scheduling, quota handling, or provider submissions.