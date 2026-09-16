# QA Report: FR-20260916-time-crystal-noisy-simulation-model

**Decision:** PASS

| # | Acceptance criterion | Evidence | Result |
|---|---|---|---|
| 1 | Typed noise configuration, explicit seeds, frozen protocol | `tests/test_time_crystal_noisy.py::test_noisy_run_replays_with_typed_provenance_and_separate_source` | PASS |
| 2 | Provenance and reproducibility metadata preserved | Same replay test and v2 round-trip test | PASS |
| 3 | Ideal and noisy evidence remain separate | Noisy source is `aer_noisy_simulation`; ideal baseline is diagnostic-only | PASS |
| 4 | Baseline, noise dominance, lifetime, and finite-size diagnostics | Noisy focused tests assert all diagnostic surfaces | PASS |
| 5 | Failed or incomplete controls never become supported | High-noise/small-system test asserts inconclusive or invalid | PASS |
| 6 | v2 round-trip and v1 ideal reads | `test_noisy_v2_round_trip_and_v1_ideal_read_are_compatible` | PASS |
| 7 | Focused deterministic replay, provenance, separation, mechanism discrimination, and false-positive tests | 21 focused tests passed, including `test_depolarizing_evolution_is_distinct_from_readout_noise` | PASS |

Playwright: N/A, no HTML or output files changed.

Validation command: `C:\G\python.exe -m pytest -q tests/test_time_crystal_dynamics.py tests/test_time_crystal_noisy.py tests/test_time_crystal_robustness.py`

Result: 21 passed. `src/time_crystal` compileall also passed. The regression test proves depolarizing noise changes the evolved state through a Pauli channel while readout noise remains a measurement-layer bit flip; the two configurations retain distinct noise digests and mechanism metadata.