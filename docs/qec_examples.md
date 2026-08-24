# Local QEC Examples

`src.qec_examples` contains small, credential-free examples for learning how
syndrome extraction and correction work. Both public functions default to the
local Qiskit Aer simulator and accept deterministic single-qubit Pauli faults.
Use `backend="python"` to exercise the decoder without constructing a circuit.

## Repetition code

`run_repetition_code(logical_bit, distance, faults)` encodes a computational
basis bit in an odd number of data qubits. Adjacent parity checks form the
syndrome. A single X fault has a unique syndrome and is corrected. The code
does not protect phase, so a Z fault is returned as uncorrectable. Two or more
faults are reported as ambiguous instead of guessed. Distances 3, 5, and other
odd distances are supported; a repetition circuit has `distance` data qubits.

## Surface-code teaching patch

`run_surface_code(logical_bit, distance, faults)` uses a fixed 3 by 3 data
patch for distance 3. Four X-check and four Z-check bits are combined into the
returned syndrome. The lookup table gives each data-qubit X or Z fault a
deterministic signature, allowing one Pauli fault to be corrected. The nine
data qubits are initialized, faulted, and measured through Aer when the default
backend is used.

This is a teaching example, not a fault-tolerant surface-code implementation:
it does not model repeated syndrome rounds, measurement faults, lattice
surgery, logical gates, a general decoder, or stochastic noise. It supports
only distance 3 and at most one expected fault for successful correction.

## Result contract

Both functions return the frozen `QECResult` dataclass with `syndrome`,
`applied_correction`, `logical_outcome`, `correctable`, `reason`, `backend`,
and deterministic Aer `counts`. Malformed inputs always raise `ValueError`.
With `strict=True`, an expected uncorrectable fault also raises `ValueError`;
the default is a structured failure result.

## Run the examples

From the Quantum project root:

```powershell
C:\G\python.exe tools\run_qec_examples.py
```

The command runs entirely locally and does not read IBM credentials.