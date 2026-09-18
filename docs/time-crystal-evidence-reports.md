# Time-Crystal Evidence Reports

`time_crystal.evidence_report` provides a bounded, versioned JSON contract for
comparative time-crystal results. It wraps the existing in-memory
`ComparativeRequest` and `ComparativeMatrix` types without changing runner
classification or simulation behavior.

## Writing a Report

```python
from time_crystal import build_evidence_report, run_comparative_matrix

matrix = run_comparative_matrix(request)
report = build_evidence_report(request, matrix)
payload = report.to_json()
```

The `v1` payload records the requested protocol, noise models, perturbations,
system sizes, seed, bounded case counts, case identity digests, public
classification, typed evidence, diagnostics, provenance, reproducibility
metadata, and explicit unavailable evidence details. Serialization uses sorted
keys and compact separators, rejects non-finite JSON constants, and preserves
Python numeric values through typed round-trip parsing.

## Loading and Replaying

```python
from time_crystal import EvidenceReport, replay_evidence_report

restored = EvidenceReport.from_json(payload)
replay = replay_evidence_report(restored, request)
assert replay.matched
```

Loading fails closed for malformed payloads and schema versions newer than
`v1`. Replay validates the request digest, case count, classification, case
identity digest, and serialized evidence. A mismatch raises
`ReplayValidationError`; no new simulation or persistence mechanism is
introduced by the report contract.