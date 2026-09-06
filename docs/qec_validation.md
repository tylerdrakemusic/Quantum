# Repetition-Code QEC Validation

This track is a bounded, local validation experiment for the repetition code.
It is intentionally separate from the existing deterministic teaching examples
and does not change the distance-3 surface-code patch.

## Operator workflow

Run the fixed seeded matrix from the repository root:

```text
$env:PYTHONPATH="src"
C:\G\python.exe tools\run_qec_validation.py
```

The command checks 81 cases: distances 3, 5, and 7; repeated syndrome rounds
3, 5, and 9; and independent data Pauli-X and syndrome-measurement fault rates
0.001, 0.005, and 0.01. The checked-in seed is `20260906`. A nonzero exit or
baseline drift is a validation failure, not a reason to update the baseline
without reviewing the model change.

Each result records the seed, odd distance, round count, both fault rates,
logical input and outcome, decoder status, decoder success, logical error, and
the normalized QEC provenance manifest. The manifest carries TODO 552 as the
provenance owner, the replayable flag, validation version, and tolerance
version.

## Decoder behavior

The baseline decoder accepts only a clean syndrome or a syndrome matching one
data-qubit X fault. Malformed values and lengths are reported as `malformed`.
Patterns that can only be treated as bounded multi-fault candidates are
reported as `ambiguous` or `uncorrectable`; the decoder never guesses a
correction for those cases. `replay_validation` routes a run through the
normalized seeded `qec` replay contract.

## Interpretation limits

This is not a threshold study, a production decoder, or a hardware result. It
uses a classical seeded simulator, independent Bernoulli fault injection, and
majority aggregation across noisy syndrome rounds. It does not model correlated
noise, leakage, erasure, realistic device calibration, Aer device-noise
channels, IBM hardware execution, or surface-code decoding. The regression
digest detects accidental drift in this exact model; it does not establish
physical accuracy.