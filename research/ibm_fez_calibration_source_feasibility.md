# `ibm_fez` Calibration-Source Feasibility

## Summary

IBM Quantum backend properties are a feasible source for documenting the
calibration state observed for `ibm_fez`, provided each calibration snapshot is
kept with its backend name, provider source, retrieval time, and IBM-supplied
update timestamp. This is suitable for analysis, provenance, and freshness
gates; it is not a reason to alter the scheduled benchmark path or to claim
that a local simulator reproduces the QPU.

## Feasibility

**Verdict: feasible for read-only observation and research documentation.**

The canonical source is the IBM Quantum backend-properties response obtained
from the selected `ibm_fez` backend. The response can expose calibration-related
values such as gate error, readout error, $T_1$, $T_2$, frequency, and the
backend's `last_update_date`. Backend configuration and status are useful
context, but they are not substitutes for calibration properties.

This source is sufficient to answer questions such as:

- Which backend and provider supplied the values?
- When did IBM report the calibration snapshot was updated?
- When did this project retrieve the snapshot?
- Which qubits and gates had properties available at that time?

It is not sufficient to reconstruct every physical detail of a run. IBM may
change calibrations during queueing or execution, and a job can be routed or
transpiled in ways that make a whole-device snapshot an imperfect description
of the circuits that actually ran.

## Provenance

Every retained calibration snapshot should record, at minimum:

| Field | Meaning |
|---|---|
| `backend_name` | The exact IBM backend identifier, expected here to be `ibm_fez` |
| `provider` | IBM Quantum service or account context, without tokens or credentials |
| `source` | IBM backend-properties API response, including the API/library version when known |
| `calibration_snapshot` | The raw or losslessly serialized properties payload, subject to repository data policy |
| `last_update_date` | IBM's timestamp for the properties snapshot, when supplied |
| `retrieved_at` | UTC timestamp recorded by this project when the source was read |
| `circuit_context` | Optional circuit, qubit, gate, and transpilation metadata used in the analysis |

Do not infer calibration provenance from an Aer result, a benchmark result, or
the project cache. Do not store IBM API tokens, account secrets, or credentials
in a snapshot or research artifact.

## Freshness Rules

Freshness must use the IBM-supplied `last_update_date` when available and keep
`retrieved_at` separately. The two timestamps answer different questions:

- **Calibration age:** `retrieved_at - last_update_date`.
- **Observation age:** current UTC time minus `retrieved_at`.

Use these labels for analysis unless a later FR establishes a stricter policy:

| Label | Rule | Permitted use |
|---|---|---|
| `fresh` | Calibration update is no more than 24 hours old and retrieval is no more than 24 hours old | Current calibration analysis |
| `aging` | Either age is over 24 hours but no more than 7 days | Historical comparison only; disclose age |
| `stale` | Either age is over 7 days | Do not use for current-state conclusions |
| `undated` | IBM omits `last_update_date` or the timestamp cannot be parsed | Provenance record only; never silently call it fresh |

If the source cannot be retrieved, record the failure and preserve the last
known snapshot as historical data. Never silently substitute Aer data for a
missing IBM calibration source. A future implementation may turn these rules
into a read-only validator, but this FR does not add one.

## IBM-to-Aer Mapping Limitations

Qiskit Aer can construct an approximate noise model from backend properties in
supported Qiskit versions, but that mapping is not an IBM calibration replay.
Aer cannot reproduce the live `ibm_fez` control stack, pulse schedules,
cross-talk, drift during a job, queue-time changes, measurement mitigation,
runtime compilation details, or all provider-specific error mechanisms.

Use these mapping labels explicitly:

- `supported`: Aer can construct a noise model from the reported properties in
	a supported Qiskit version.
- `approximate`: the resulting local noise model is derived from selected IBM
	properties and is not hardware-equivalent.
- `unsupported`: live control-stack behavior, pulse schedules, cross-talk,
	drift, queue-time changes, mitigation, and provider-specific mechanisms are
	outside Aer's supported mapping.

The mapping is therefore useful for sensitivity studies and controlled local
comparisons only. It must be labeled as **Aer with an IBM-derived approximate noise model**,
not as `ibm_fez`, hardware output, or a fresh calibration snapshot. A noiseless Aer run is even further removed: it is a mathematical
simulator baseline and has no IBM calibration provenance.

The following distinctions must remain explicit:

| Artifact | What it represents | What it cannot claim |
|---|---|---|
| IBM backend properties | A provider-reported calibration snapshot | Exact conditions of every queued or executed circuit |
| Aer noise model derived from properties | A local approximation based on selected reported parameters | Hardware equivalence or live calibration fidelity |
| Noiseless Aer | An idealized local reference | Physical error behavior or QPU provenance |
| IBM job result | A measurement from a real backend at execution time | A reusable, timeless calibration snapshot |

## Scope Boundary

This note documents feasibility, provenance, freshness rules, and simulator
limitations only. It does not change benchmark behavior, live scheduling,
execution policy, QPU selection or fallback, provider calls in scheduled
benchmarks, cache filling, or result interpretation.

## References

- IBM Quantum documentation: [Backend properties](https://quantum.cloud.ibm.com/docs/en/guides/get-qpu-information#backend-properties)
- Qiskit Aer documentation: [`NoiseModel.from_backend`](https://qiskit.github.io/qiskit-aer/stubs/qiskit_aer.noise.NoiseModel.html)
- Qiskit IBM Runtime API reference: [BackendV2 properties](https://quantum.cloud.ibm.com/docs/api/qiskit-ibm-runtime/qiskit_ibm_runtime.IBMBackend#properties)