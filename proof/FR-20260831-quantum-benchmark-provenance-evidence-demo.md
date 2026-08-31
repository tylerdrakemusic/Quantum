# FR-20260831 Quantum benchmark provenance demo

The working demonstration is the real-database regression in
`tests/test_benchmark_provenance.py`.

It exercises the public `adapt_result` contract for all five benchmark
families, writes each manifest through `persist_manifest`, reads the stored
family/version/status/reference columns back, and proves the pre-existing
legacy benchmark row is unchanged. The focused Shor and VQE suites also pass
with their existing database writer paths loaded.

No hardware job or quantum-provider credential is required for this proof.