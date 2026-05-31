"""BB84 Quantum Key Distribution protocol simulation.

FR-20260530-qkd-bb84-test-harness

Implements the BB84 protocol with two backends:
  - 'python': Pure NumPy state-vector simulation
  - 'qiskit': Qiskit Aer QuantumCircuit simulation

Exports:
    Alice          -- encodes classical bits into qubit states
    Bob            -- measures qubit states in a chosen basis
    Eve            -- intercept-resend eavesdropper
    run_bb84()     -- full protocol simulation
    calculate_qber() -- Quantum Bit Error Rate
"""
from __future__ import annotations

from typing import List

import numpy as np


# ---------------------------------------------------------------------------
# Pure-Python state vector helpers
# ---------------------------------------------------------------------------

_SQ2 = 1.0 / np.sqrt(2)

# Basis state vectors
_STATES = {
    ("Z", 0): np.array([1.0, 0.0]),   # |0⟩
    ("Z", 1): np.array([0.0, 1.0]),   # |1⟩
    ("X", 0): np.array([_SQ2, _SQ2]),  # |+⟩
    ("X", 1): np.array([_SQ2, -_SQ2]), # |−⟩
}

# Measurement basis vectors for projective measurement
_MEAS_BASIS = {
    "Z": (np.array([1.0, 0.0]), np.array([0.0, 1.0])),  # |0⟩, |1⟩
    "X": (np.array([_SQ2, _SQ2]), np.array([_SQ2, -_SQ2])),  # |+⟩, |−⟩
}


def _measure_state(state: np.ndarray, basis: str, rng: np.random.Generator) -> int:
    """Project state vector onto basis; return 0 or 1 according to Born rule."""
    ket0, _ = _MEAS_BASIS[basis]
    prob0 = abs(np.dot(ket0.conj(), state)) ** 2
    return 0 if rng.random() < prob0 else 1


# ---------------------------------------------------------------------------
# Alice
# ---------------------------------------------------------------------------

class Alice:
    """Encodes classical bits into qubit state vectors using BB84 encoding.

    Z basis: 0 → |0⟩,  1 → |1⟩
    X basis: 0 → |+⟩,  1 → |−⟩
    """

    def __init__(self, rng: np.random.Generator | None = None) -> None:
        self._rng = rng if rng is not None else np.random.default_rng()

    def random_bits(self, n: int) -> List[int]:
        return self._rng.integers(0, 2, size=n).tolist()

    def random_bases(self, n: int) -> List[str]:
        return ["Z" if b == 0 else "X" for b in self._rng.integers(0, 2, size=n)]

    def encode(self, bit: int, basis: str) -> np.ndarray:
        """Return the 2-element state vector for (bit, basis).

        Args:
            bit:   0 or 1
            basis: 'Z' or 'X'

        Returns:
            NumPy array of shape (2,) representing the qubit state vector.
        """
        return _STATES[(basis, bit)].copy()


# ---------------------------------------------------------------------------
# Bob
# ---------------------------------------------------------------------------

class Bob:
    """Measures qubit states in a specified basis.

    Matching basis → deterministic outcome.
    Mismatched basis → outcome is random (Born-rule probability).
    """

    def __init__(self, rng: np.random.Generator | None = None) -> None:
        self._rng = rng if rng is not None else np.random.default_rng()

    def random_bases(self, n: int) -> List[str]:
        return ["Z" if b == 0 else "X" for b in self._rng.integers(0, 2, size=n)]

    def measure(self, state: np.ndarray, basis: str) -> int:
        """Measure state vector in the given basis.

        Args:
            state: 2-element qubit state vector.
            basis: 'Z' or 'X'.

        Returns:
            Measured bit: 0 or 1.
        """
        return _measure_state(state, basis, self._rng)


# ---------------------------------------------------------------------------
# Eve
# ---------------------------------------------------------------------------

class Eve:
    """Implements an intercept-resend eavesdropping attack.

    Eve measures each qubit in a randomly chosen basis and re-prepares a
    fresh qubit in the state corresponding to her measurement outcome.
    This introduces ~25 % errors in the final sifted key.
    """

    def __init__(self, rng: np.random.Generator | None = None) -> None:
        self._rng = rng if rng is not None else np.random.default_rng()

    def random_bases(self, n: int) -> List[str]:
        return ["Z" if b == 0 else "X" for b in self._rng.integers(0, 2, size=n)]

    def intercept(self, state: np.ndarray, eve_basis: str) -> np.ndarray:
        """Measure state in eve_basis; re-prepare and return new state.

        Args:
            state:     Incoming 2-element qubit state vector from Alice.
            eve_basis: Basis Eve uses for her measurement ('Z' or 'X').

        Returns:
            New state vector Eve forwards to Bob.
        """
        measured_bit = _measure_state(state, eve_basis, self._rng)
        return _STATES[(eve_basis, measured_bit)].copy()


# ---------------------------------------------------------------------------
# Pure-Python BB84 run
# ---------------------------------------------------------------------------

def _run_bb84_python(n_bits: int, include_eve: bool, rng: np.random.Generator) -> dict:
    """NumPy state-vector BB84 simulation."""
    alice = Alice(rng)
    bob = Bob(rng)

    alice_bits = alice.random_bits(n_bits)
    alice_bases = alice.random_bases(n_bits)
    bob_bases = bob.random_bases(n_bits)

    # Alice encodes each bit
    states = [alice.encode(bit, basis) for bit, basis in zip(alice_bits, alice_bases)]

    # Eve optionally intercepts
    if include_eve:
        eve = Eve(rng)
        eve_bases = eve.random_bases(n_bits)
        states = [eve.intercept(s, eb) for s, eb in zip(states, eve_bases)]

    # Bob measures in his (independently chosen) basis
    bob_bits = [bob.measure(s, basis) for s, basis in zip(states, bob_bases)]

    # Basis sifting: keep positions where Alice and Bob used the same basis
    alice_sifted: List[int] = []
    bob_sifted: List[int] = []
    for ab, bb, a_bit, b_bit in zip(alice_bases, bob_bases, alice_bits, bob_bits):
        if ab == bb:
            alice_sifted.append(a_bit)
            bob_sifted.append(b_bit)

    return {
        "alice_key": alice_sifted,
        "bob_key": bob_sifted,
        "alice_bases": alice_bases,
        "bob_bases": bob_bases,
        "n_raw": n_bits,
        "n_sifted": len(alice_sifted),
    }


# ---------------------------------------------------------------------------
# Qiskit Aer BB84 run
# ---------------------------------------------------------------------------

def _run_bb84_qiskit(n_bits: int, include_eve: bool, rng: np.random.Generator) -> dict:
    """Qiskit Aer BB84 simulation using QuantumCircuit with H/X gates."""
    from qiskit import QuantumCircuit, transpile  # type: ignore
    from qiskit_aer import AerSimulator  # type: ignore

    simulator = AerSimulator()

    alice_bits = [int(x) for x in rng.integers(0, 2, size=n_bits)]
    alice_bases = ["Z" if b == 0 else "X" for b in rng.integers(0, 2, size=n_bits)]
    bob_bases = ["Z" if b == 0 else "X" for b in rng.integers(0, 2, size=n_bits)]

    def _alice_circuit(bit: int, basis: str) -> QuantumCircuit:
        """Build Alice's state-preparation circuit (no measurement)."""
        qc = QuantumCircuit(1)
        if bit == 1:
            qc.x(0)      # flip to |1⟩
        if basis == "X":
            qc.h(0)      # transform to |±⟩
        return qc

    def _run_circuits(circuits: list) -> List[int]:
        """Transpile, run with shots=1, return bit outcomes."""
        transpiled = transpile(circuits, simulator)
        job = simulator.run(transpiled, shots=1)
        result = job.result()
        outcomes: List[int] = []
        for i in range(len(circuits)):
            counts = result.get_counts(i)
            # counts key is a bitstring, e.g. '0' or '1'
            measured = int(max(counts, key=counts.get))
            outcomes.append(measured)
        return outcomes

    if include_eve:
        eve_bases = ["Z" if b == 0 else "X" for b in rng.integers(0, 2, size=n_bits)]
        eve_bits_raw = [int(x) for x in rng.integers(0, 2, size=n_bits)]  # unused but kept for symmetry

        # Phase 1: Alice prepares, Eve measures in her chosen basis
        phase1: List[QuantumCircuit] = []
        for i in range(n_bits):
            qc = _alice_circuit(alice_bits[i], alice_bases[i])
            qc.add_register(__import__("qiskit").ClassicalRegister(1))
            if eve_bases[i] == "X":
                qc.h(0)
            qc.measure(0, 0)
            phase1.append(qc)

        eve_measured = _run_circuits(phase1)

        # Phase 2: Eve re-prepares in her basis, Bob measures in his basis
        phase2: List[QuantumCircuit] = []
        for i in range(n_bits):
            qc = QuantumCircuit(1, 1)
            if eve_measured[i] == 1:
                qc.x(0)
            if eve_bases[i] == "X":
                qc.h(0)
            if bob_bases[i] == "X":
                qc.h(0)
            qc.measure(0, 0)
            phase2.append(qc)

        bob_bits = _run_circuits(phase2)
    else:
        # Alice → Bob directly
        circuits: List[QuantumCircuit] = []
        for i in range(n_bits):
            qc = _alice_circuit(alice_bits[i], alice_bases[i])
            qc.add_register(__import__("qiskit").ClassicalRegister(1))
            if bob_bases[i] == "X":
                qc.h(0)
            qc.measure(0, 0)
            circuits.append(qc)

        bob_bits = _run_circuits(circuits)

    # Basis sifting
    alice_sifted: List[int] = []
    bob_sifted: List[int] = []
    for ab, bb, a_bit, b_bit in zip(alice_bases, bob_bases, alice_bits, bob_bits):
        if ab == bb:
            alice_sifted.append(a_bit)
            bob_sifted.append(b_bit)

    return {
        "alice_key": alice_sifted,
        "bob_key": bob_sifted,
        "alice_bases": alice_bases,
        "bob_bases": bob_bases,
        "n_raw": n_bits,
        "n_sifted": len(alice_sifted),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_bb84(
    n_bits: int = 256,
    backend: str = "python",
    include_eve: bool = False,
) -> dict:
    """Run a BB84 QKD protocol simulation.

    Args:
        n_bits:      Number of raw qubits to transmit.
        backend:     'python' (NumPy) or 'qiskit' (Qiskit Aer).
        include_eve: Whether Eve performs an intercept-resend attack.

    Returns:
        dict with keys:
            alice_key   -- Alice's sifted key (List[int])
            bob_key     -- Bob's sifted key (List[int])
            alice_bases -- Alice's basis choices (List[str])
            bob_bases   -- Bob's basis choices (List[str])
            n_raw       -- number of raw qubits transmitted (int)
            n_sifted    -- length of the sifted key (int)
    """
    rng = np.random.default_rng()
    if backend == "python":
        return _run_bb84_python(n_bits, include_eve, rng)
    if backend == "qiskit":
        return _run_bb84_qiskit(n_bits, include_eve, rng)
    raise ValueError(f"Unknown backend: {backend!r}. Use 'python' or 'qiskit'.")


def calculate_qber(alice_key: List[int], bob_key: List[int]) -> float:
    """Calculate the Quantum Bit Error Rate between two sifted keys.

    Args:
        alice_key: Alice's sifted key bits.
        bob_key:   Bob's sifted key bits.

    Returns:
        QBER as a float in [0.0, 1.0]. Returns 0.0 for empty keys.
    """
    if not alice_key or not bob_key:
        return 0.0
    n = min(len(alice_key), len(bob_key))
    errors = sum(a != b for a, b in zip(alice_key[:n], bob_key[:n]))
    return errors / n
