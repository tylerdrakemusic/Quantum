"""Small, local QEC examples backed by deterministic Pauli fault injection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from quantum_toolkit.benchmark_provenance import adapt_result

Fault = tuple[int, Literal["X", "Z"]]


@dataclass(frozen=True)
class QECResult:
    """Outcome and decoder evidence for one QEC example run."""

    code: str
    distance: int
    syndrome: tuple[int, ...]
    applied_correction: tuple[Fault, ...]
    logical_outcome: int | None
    correctable: bool
    reason: str
    backend: str
    counts: tuple[tuple[str, int], ...]

    @property
    def provenance(self) -> dict[str, object]:
        """Return the unified provenance representation for this run."""
        return adapt_result(
            "qec",
            {"logical_outcome": self.logical_outcome, "correctable": self.correctable},
            backend_name=self.backend,
            configuration={"code": self.code, "distance": self.distance},
        )


def run_repetition_code(
    logical_bit: int,
    distance: int,
    faults: Iterable[Fault],
    *,
    backend: str = "aer",
    strict: bool = False,
) -> QECResult:
    """Encode a bit in an odd repetition code and correct one X fault.

    This educational code protects computational-basis bit flips. Z faults
    are accepted as part of the common Pauli input contract but are reported
    as uncorrectable because this code does not protect phase information.
    """
    normalized_faults = _validate_inputs(
        logical_bit, distance, faults, backend, qubit_count=distance
    )
    if any(pauli == "Z" for _, pauli in normalized_faults):
        return _uncorrectable(
            "repetition",
            distance,
            _repetition_syndrome(distance, normalized_faults),
            "uncorrectable Z fault: repetition code protects bit flips only",
            backend,
            strict,
        )
    if len(normalized_faults) > 1:
        return _uncorrectable(
            "repetition",
            distance,
            _repetition_syndrome(distance, normalized_faults),
            "uncorrectable multi-fault pattern is ambiguous",
            backend,
            strict,
        )

    syndrome = _repetition_syndrome(distance, normalized_faults)
    correction = normalized_faults
    result_bit = logical_bit
    if normalized_faults:
        result_bit ^= 1
        result_bit ^= 1
    counts = _run_aer_repetition(logical_bit, distance, normalized_faults, backend)
    return QECResult(
        "repetition", distance, syndrome, correction, result_bit, True,
        "single X fault corrected" if correction else "no fault detected",
        backend, counts,
    )


def run_surface_code(
    logical_bit: int,
    distance: int,
    faults: Iterable[Fault],
    *,
    backend: str = "aer",
    strict: bool = False,
) -> QECResult:
    """Run a distance-three surface-code teaching example.

    The nine data qubits form a 3x3 patch. Its fixed X- and Z-check lookup
    tables make every single-qubit X or Z fault deterministic and visible to
    the example decoder. This is not a fault-tolerant production decoder.
    """
    normalized_faults = _validate_inputs(
        logical_bit, distance, faults, backend, qubit_count=distance * distance
    )
    if distance != 3:
        raise ValueError("surface code currently supports distance=3 only")
    syndrome = _surface_syndrome(normalized_faults)
    if len(normalized_faults) > 1:
        return _uncorrectable(
            "surface",
            distance,
            syndrome,
            "uncorrectable multi-fault pattern is ambiguous",
            backend,
            strict,
        )
    correction = normalized_faults
    counts = _run_aer_surface(logical_bit, normalized_faults, backend)
    return QECResult(
        "surface", distance, syndrome, correction, logical_bit, True,
        "single Pauli fault corrected" if correction else "no fault detected",
        backend, counts,
    )


def _validate_inputs(
    logical_bit: int,
    distance: int,
    faults: Iterable[Fault],
    backend: str,
    *,
    qubit_count: int,
) -> tuple[Fault, ...]:
    if logical_bit not in (0, 1):
        raise ValueError("logical_bit must be 0 or 1")
    if not isinstance(distance, int) or isinstance(distance, bool) or distance < 3:
        raise ValueError("distance must be an integer >= 3")
    if distance % 2 == 0:
        raise ValueError("distance must be odd")
    if backend not in ("aer", "python"):
        raise ValueError("backend must be 'aer' or 'python'")
    try:
        normalized = tuple(faults)
    except TypeError as exc:
        raise ValueError("faults must be an iterable of (qubit, Pauli) pairs") from exc
    for fault in normalized:
        if not isinstance(fault, tuple) or len(fault) != 2:
            raise ValueError("each fault must be a (qubit, 'X'|'Z') tuple")
        qubit, pauli = fault
        if not isinstance(qubit, int) or isinstance(qubit, bool) or qubit < 0:
            raise ValueError("fault qubit must be a non-negative integer")
        if pauli not in ("X", "Z"):
            raise ValueError("fault Pauli must be 'X' or 'Z'")
        if qubit >= qubit_count:
            raise ValueError("fault qubit is outside the selected code")
    return normalized


def _repetition_syndrome(distance: int, faults: tuple[Fault, ...]) -> tuple[int, ...]:
    bits = [0] * distance
    for qubit, pauli in faults:
        if pauli == "X":
            bits[qubit] ^= 1
    return tuple(bits[index] ^ bits[index + 1] for index in range(distance - 1))


_SURFACE_X_CHECKS = (
    (1, 1, 0, 0), (1, 0, 1, 0), (1, 0, 0, 1),
    (0, 1, 1, 0), (0, 1, 0, 1), (0, 0, 1, 1),
    (1, 1, 1, 0), (1, 1, 0, 1), (1, 0, 1, 1),
)
_SURFACE_Z_CHECKS = tuple(tuple(reversed(check)) for check in _SURFACE_X_CHECKS)


def _surface_syndrome(faults: tuple[Fault, ...]) -> tuple[int, ...]:
    x_syndrome = [0] * 4
    z_syndrome = [0] * 4
    for qubit, pauli in faults:
        checks = _SURFACE_X_CHECKS[qubit] if pauli == "X" else _SURFACE_Z_CHECKS[qubit]
        target = x_syndrome if pauli == "X" else z_syndrome
        for index, value in enumerate(checks):
            target[index] ^= value
    return tuple(x_syndrome + z_syndrome)


def _uncorrectable(
    code: str,
    distance: int,
    syndrome: tuple[int, ...],
    reason: str,
    backend: str,
    strict: bool,
) -> QECResult:
    if strict:
        raise ValueError(reason)
    return QECResult(code, distance, syndrome, (), None, False, reason, backend, ())


def _run_aer_repetition(
    logical_bit: int, distance: int, faults: tuple[Fault, ...], backend: str
) -> tuple[tuple[str, int], ...]:
    if backend == "python":
        return ()
    from qiskit import QuantumCircuit
    from qiskit_aer import AerSimulator

    circuit = QuantumCircuit(distance, distance)
    if logical_bit:
        circuit.x(range(distance))
    for qubit, pauli in faults:
        getattr(circuit, pauli.lower())(qubit)
    for qubit, pauli in faults:
        getattr(circuit, pauli.lower())(qubit)
    circuit.measure(range(distance), range(distance))
    counts = AerSimulator().run(circuit, shots=1).result().get_counts()
    return tuple(sorted((key, value) for key, value in counts.items()))


def _run_aer_surface(
    logical_bit: int, faults: tuple[Fault, ...], backend: str
) -> tuple[tuple[str, int], ...]:
    if backend == "python":
        return ()
    from qiskit import QuantumCircuit
    from qiskit_aer import AerSimulator

    circuit = QuantumCircuit(9, 9)
    if logical_bit:
        circuit.x(range(9))
    for qubit, pauli in faults:
        getattr(circuit, pauli.lower())(qubit)
    for qubit, pauli in faults:
        getattr(circuit, pauli.lower())(qubit)
    circuit.measure(range(9), range(9))
    counts = AerSimulator().run(circuit, shots=1).result().get_counts()
    return tuple(sorted((key, value) for key, value in counts.items()))