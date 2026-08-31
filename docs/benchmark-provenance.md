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