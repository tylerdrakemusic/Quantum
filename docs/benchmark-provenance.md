# Benchmark Provenance Contract

Quantum benchmark runs use manifest version `1.0`, implemented by
`src/quantum_toolkit/benchmark_provenance.py`. A manifest contains identity,
execution, backend, configuration, result, timestamp, and evidence references.

New Shor, VQE, QAOA, QEC, and quantum-kernel writers use the same normalized
representation. Unavailable metadata is represented as JSON `null`; writers
must not infer or fabricate it. Evidence references are paths or identifiers,
not copied evidence payloads.

Readers normalize historical rows at read time with
`provenance_status=legacy`. Historical database rows and evidence files are
never backfilled or rewritten. Fields unavailable in the old record remain
`null`, and existing algorithm-specific fields remain available for replay and
dashboard compatibility.

Future manifest versions must retain the required sections and provide an
explicit reader compatibility policy before they are emitted. Readers may
accept the current version and legacy records; unsupported future versions are
rejected rather than silently guessed.

## Replay and comparison

Local replay is seeded and records one of `pass`, `tolerance_failure`,
`unavailable`, `execution_failure`, or `nondeterministic`. The five supported
families are `shor`, `vqe`, `qaoa`, `qec`, and `quantum_kernel`. Every
comparison stores `tolerance_version` and the absolute and relative values
used. Family metrics remain separate; the dashboard deliberately does not
compute a composite score.

The current tolerance set is version `2026-09-05`. VQE energy uses an absolute
and relative tolerance of `0.02`; QAOA approximation ratio uses `0.05`; other
metrics use the default `1e-6` values until a family-specific policy is added.

## IBM Runtime operations

Runtime capture stores backend, provider, job, execution, retry, and
operational metadata after credential redaction. API keys, tokens, passwords,
secrets, and credentials must never be written to manifests, logs, proof files,
or dashboard data. A failed job is not automatically submitted by the library:
the decision record is `approval_required` until an operator explicitly
approves it. The `resubmit_runtime_job` helper then submits exactly one retry
through the injected Runtime client. Resubmission is `quota_blocked` when no
quota remains and `not_eligible` when the captured job was not failed. The
decision includes remaining quota, credential-safety, and automatic-submission
flags so an operator can audit what happened.

Before approving a resubmission, check backend availability, current quota and
cost, rate-limit state, retry count, and whether the result is nondeterministic.
An approved retry should receive a new run identity and preserve the failed
job's evidence reference. A replay comparison is scientific evidence, not a
ranking: interpret each family metric and its tolerance version independently.

## Dashboard and validation

Run `C:\G\python.exe tools\gen_benchmark_dashboard.py --no-open` to regenerate
the dashboard. The normalized replay section shows run identity, family,
outcome, seed, and tolerance version alongside the existing legacy Shor replay
section. The source `benchmarks` and `shor_replay_benchmarks` tables remain
unchanged.

Focused validation:

```text
C:\G\python.exe -m pytest tests/test_benchmark_provenance.py tests/test_benchmark_replay.py tests/test_gen_benchmark_dashboard.py -q
```