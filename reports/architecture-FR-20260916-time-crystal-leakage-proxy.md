# Architecture Impact Report: FR-20260916-time-crystal-leakage-proxy

**Decision:** PASS

The change is additive within the existing `src/time_crystal` protocol and
evidence contracts. `NoiseConfig` gains a bounded per-site, per-Floquet-period
leakage probability and a versioned digest input. `run_noisy_floquet_ising`
returns a typed unavailable result for nonzero leakage because the current
simulator has no explicit out-of-subspace representation.

No state-space expansion, measurement-only leakage, heating substitution,
database/schema change, dependency, hardware path, UI, deployment, benchmark,
randomness-cache, or cross-project change was introduced.