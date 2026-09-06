# FR-20260906 QEC Decoder Validation Evidence

## Implementation

- Added `src/quantum_toolkit/qec_validation.py` with the versioned seeded
  repetition-code contract, repeated-round simulation, bounded decoder,
  baseline digest validation, and normalized `qec` replay integration.
- Added `tests/test_qec_validation.py` covering validation boundaries,
  clean/corrected/ambiguous/uncorrectable/malformed decoder outcomes, the
  81-case matrix, provenance fields, replay, and drift detection.
- Added `research/qec_validation_baseline.json` for seed `20260906`, validation
  version `2026-09-06.1`, tolerance version `2026-09-05`, and the fixed result
  digest.
- Added `tools/run_qec_validation.py` and `docs/qec_validation.md`.

## Validation evidence

- Focused QEC and provenance suite: **30 passed** in 4.67s.
- New QEC validation suite: **6 passed**.
- Operator demo: **81 cases**, validation `pass`, **81 decoder successes**,
  **0 logical errors** for the checked-in seed.
- Focused coverage: **93%** for `qec_validation.py`.
- `compileall` and `git diff --check`: passed.
- Full non-Playwright suite: 227 selected; existing `tests/test_vqe.py`
  exceeded the 60-second timeout after the changed tests and other suites had
  passed. This is recorded as a pre-existing/unrelated full-suite blocker, not
  claimed as a green full run.

## Gate and bookkeeping status

- FR ledger state remains `BRANCHED`; no finality transition was attempted.
- Required child chain TODO 559, 560, 561, 562, 563 was not advanced because
  the manifest-coordination MCP was degraded and the local manifest DB has no
  TODO rows. Parent-join bookkeeping therefore remains explicitly pending.
- Playwright, SQLite, filesystem, and coordination MCPs reported degraded
  status in the preflight file. No UI or hardware execution was required.