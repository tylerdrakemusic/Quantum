# FR-20260831 Quantum benchmark provenance persistence proof

## Acceptance coverage

- `benchmark_provenance` is additive. Existing `benchmarks`, `vqe_runs`, and
  `shors_qpu_bench` rows keep their legacy columns and are never rewritten.
- Every new persisted manifest has `manifest_version` `1.0`, a family identity,
  a required run id, a provenance status, serialized manifest content, and a
  JSON evidence-reference list.
- The canonical persistence regression covers all five families: `shor`,
  `vqe`, `qaoa`, `qec`, and `quantum_kernel`.
- Legacy normalization keeps unavailable fields explicitly null and does not
  mutate the source mapping.
- The VQE and Shor database writers persist their existing result row and the
  corresponding manifest. QEC and quantum-kernel results emit the same
  versioned contract through their existing result properties. QAOA is covered
  by the shared writer contract because the historical QAOA solver is no longer
  present in this branch or public package API.

## Reproduction

From the isolated feature worktree:

```text
$env:PYTHONPATH='src;src\\utils'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
C:\\G\\python.exe -m pytest -q tests/test_benchmark_provenance.py tests/test_run_shors_bench.py tests/test_run_vqe_bench.py
20 passed
```

The persistence test inserts one legacy `benchmarks` row, persists one manifest
for each required family, and verifies that the legacy row remains exactly
`legacy-shor` / `old-aer`. It also verifies that an empty evidence list is
stored as `[]`, while historical normalization returns null for unavailable
manifest fields.

## Demo result

The test database contained five new rows in `benchmark_provenance`, one per
family, each with manifest version `1.0` and status `provenance`. No historical
row was migrated or updated.