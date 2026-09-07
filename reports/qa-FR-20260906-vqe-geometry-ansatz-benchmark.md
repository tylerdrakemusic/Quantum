# QA Report: FR-20260906-vqe-geometry-ansatz-benchmark

**Decision:** PASS

| # | Acceptance criterion | Test/evidence | Result |
|---|---|---|---|
| 1 | The bounded matrix uses only genuine committed H2 0.7414 A and LiH 1.45 A fixtures. | `tests/test_vqe.py` fixture contract; CLI help for `tools/bench_vqe.py` and `tools/run_vqe_bench.py`; no `h2_1.50` or `1.50` references remain in `tools`, `src`, `tests`, `research`, or `docs`. | PASS |
| 2 | UCCSD and EfficientSU2 remain supported with deterministic bounded local execution. | Focused VQE and guarded-runner tests: 18 passed, 1 deselected; deterministic EfficientSU2 contract and seed forwarding passed. | PASS |
| 3 | Baseline VQE behavior remains compatible. | H2 chemical-accuracy test passed; existing LiH slow/CI-long-running contract remains present and excluded from the focused run. | PASS |
| 4 | Provenance and replay metadata remain preserved. | Regression slice `tests/test_benchmark_provenance.py tests/test_benchmark_replay.py`: 17 passed. | PASS |
| 5 | Dashboard geometry/ansatz comparison remains available. | `tests/test_gen_benchmark_dashboard.py`: 7 passed; fixture data covers H2 0.7414 A and LiH 1.45 A with both ansatz labels. | PASS |
| 6 | QPU access remains explicit and budget-gated. | `tests/test_run_vqe_bench.py`: 8 passed; CLI retains `--backend {aer,qpu}`, shared-budget fallback, wall-clock guard, and QPU estimator forwarding. | PASS |

## Regression and Build Checks

- Focused feature slice: 18 passed, 1 deselected in 39.90 seconds.
- Provenance/replay/policy regression slice: 25 passed in 5.08 seconds.
- Changed benchmark modules compiled successfully with `compileall`.
- `git diff --check` passed.
- Playwright: N/A. The worktree diff changes Python and test sources only; no HTML or `output/` artifact is part of this FR implementation.
- Architecture impact: none. No new dependencies, database tables, integrations, agents, or cross-project wiring.

## Notes

The pre-existing generated image deletion is unrelated worktree churn and is excluded from this FR report. The H2 1.50 A request is deferred until a genuine geometry-specific fixture exists; no placeholder execution target remains.