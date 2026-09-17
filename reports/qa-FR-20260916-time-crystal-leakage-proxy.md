# QA Report: FR-20260916-time-crystal-leakage-proxy

**Decision:** PASS for the support-gated unsupported path

The existing simulator keeps a fixed `2**system_size` in-subspace state vector
and has no explicit out-of-subspace extension point. The implementation does
not expand that representation, add measurement-only leakage, or substitute
heating. A nonzero leakage request returns `ValidationStatus.UNAVAILABLE` with
an `EvidenceUnavailable` reason, protocol digest, noise digest, model version,
requested observable, and leakage observable metadata.

Focused validation:

```text
C:\G\python.exe -m pytest -q tests/test_time_crystal_dynamics.py tests/test_time_crystal_noisy.py tests/test_time_crystal_robustness.py
31 passed
C:\G\python.exe -m compileall -q src/time_crystal
passed
```

Leakage-specific coverage includes bounds, versioned digest inputs, typed
unsupported provenance, deterministic replay, and JSON round-trip. Existing
depolarizing, readout, and coherent-noise composition tests remain green with
the default leakage probability of `0.0`.