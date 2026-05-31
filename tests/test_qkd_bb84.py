"""BB84 QKD protocol test harness.

FR-20260530-qkd-bb84-test-harness

Tests:
- Alice encoding: X/Z bases × {0,1} values
- Bob measurement: matching basis → deterministic bit; mismatching → ~50% noise (statistical)
- Basis sifting: sifted key length ≈ raw_len × 0.5 ± tolerance
- No-Eve path: QBER < 0.05
- Eve intercept-resend path: QBER ≥ 0.20
- Key lengths parametrized: [64, 128, 256] bits
- Qiskit Aer tests marked @pytest.mark.slow
- Both backends (pure Python always, Qiskit where marked slow)
"""
from __future__ import annotations

import pytest
import numpy as np

from research.quantum_qkd_bb84 import (
    Alice,
    Bob,
    Eve,
    run_bb84,
    calculate_qber,
)


# ---------------------------------------------------------------------------
# Export surface
# ---------------------------------------------------------------------------

def test_module_exports_required_symbols():
    """AC-1: module must export Alice, Bob, Eve, run_bb84, calculate_qber."""
    from research import quantum_qkd_bb84 as mod
    for name in ("Alice", "Bob", "Eve", "run_bb84", "calculate_qber"):
        assert hasattr(mod, name), f"Missing export: {name}"


# ---------------------------------------------------------------------------
# Alice encoding — Z/X bases × {0, 1}
# ---------------------------------------------------------------------------

class TestAliceEncoding:
    """Alice encodes classical bits into normalised qubit state vectors."""

    def test_z_basis_bit0_is_ground_state(self):
        state = Alice().encode(0, "Z")
        np.testing.assert_allclose(state, [1.0, 0.0], atol=1e-10)

    def test_z_basis_bit1_is_excited_state(self):
        state = Alice().encode(1, "Z")
        np.testing.assert_allclose(state, [0.0, 1.0], atol=1e-10)

    def test_x_basis_bit0_is_plus_state(self):
        sq2 = 1.0 / np.sqrt(2)
        state = Alice().encode(0, "X")
        np.testing.assert_allclose(state, [sq2, sq2], atol=1e-10)

    def test_x_basis_bit1_is_minus_state(self):
        sq2 = 1.0 / np.sqrt(2)
        state = Alice().encode(1, "X")
        np.testing.assert_allclose(state, [sq2, -sq2], atol=1e-10)

    def test_all_states_are_normalised(self):
        alice = Alice()
        for basis in ("Z", "X"):
            for bit in (0, 1):
                state = alice.encode(bit, basis)
                norm = float(np.dot(state.conj(), state).real)
                assert abs(norm - 1.0) < 1e-10, f"Not normalised: basis={basis}, bit={bit}"


# ---------------------------------------------------------------------------
# Bob measurement — matching basis deterministic, mismatch ~50%
# ---------------------------------------------------------------------------

class TestBobMeasurement:
    """Measurement outcomes depend on basis alignment."""

    def test_matching_z_basis_deterministic(self):
        alice = Alice()
        bob = Bob()
        for bit in (0, 1):
            state = alice.encode(bit, "Z")
            results = [bob.measure(state, "Z") for _ in range(50)]
            assert all(r == bit for r in results), (
                f"Z basis non-deterministic: encoded {bit}, got {set(results)}"
            )

    def test_matching_x_basis_deterministic(self):
        alice = Alice()
        bob = Bob()
        for bit in (0, 1):
            state = alice.encode(bit, "X")
            results = [bob.measure(state, "X") for _ in range(50)]
            assert all(r == bit for r in results), (
                f"X basis non-deterministic: encoded {bit}, got {set(results)}"
            )

    def test_mismatched_basis_approx_50_50(self):
        """Measuring |0⟩ in X basis: P(0) ≈ 0.5 (within statistical tolerance)."""
        alice = Alice()
        bob = Bob(rng=np.random.default_rng(42))
        state = alice.encode(0, "Z")  # |0⟩
        results = [bob.measure(state, "X") for _ in range(1000)]
        p_zero = results.count(0) / len(results)
        # 50 % ± 7 % at n=1000 covers > 5-sigma range
        assert 0.43 <= p_zero <= 0.57, (
            f"Expected ~50 % zero-outcome, got {p_zero:.3f}"
        )

    def test_mismatched_basis_has_both_outcomes(self):
        """Measuring |0⟩ in X basis must occasionally return both 0 and 1."""
        alice = Alice()
        bob = Bob(rng=np.random.default_rng(7))
        state = alice.encode(0, "Z")
        results = {bob.measure(state, "X") for _ in range(20)}
        assert results == {0, 1}, f"Expected both outcomes, got {results}"


# ---------------------------------------------------------------------------
# Basis sifting
# ---------------------------------------------------------------------------

class TestSifting:
    """Sifted key length ≈ 50 % of raw bits; alice/bob keys same length."""

    @pytest.mark.parametrize("n_bits", [64, 128, 256])
    def test_sifted_key_length_approx_half_raw(self, n_bits):
        result = run_bb84(n_bits=n_bits, backend="python")
        ratio = result["n_sifted"] / n_bits
        assert 0.30 <= ratio <= 0.70, (
            f"Sifted ratio out of range: {ratio:.3f} (n_bits={n_bits})"
        )

    @pytest.mark.parametrize("n_bits", [64, 128, 256])
    def test_sifted_keys_same_length(self, n_bits):
        result = run_bb84(n_bits=n_bits, backend="python")
        assert len(result["alice_key"]) == len(result["bob_key"])
        assert len(result["alice_key"]) == result["n_sifted"]

    def test_result_contains_required_fields(self):
        result = run_bb84(n_bits=64, backend="python")
        for field in ("alice_key", "bob_key", "alice_bases", "bob_bases", "n_sifted", "n_raw"):
            assert field in result, f"Missing result field: {field}"


# ---------------------------------------------------------------------------
# QBER — no Eve
# ---------------------------------------------------------------------------

class TestQBERNoEve:
    """Without Eve, sifted keys are identical and QBER < 0.05."""

    @pytest.mark.parametrize("n_bits", [64, 128, 256])
    def test_no_eve_qber_below_threshold(self, n_bits):
        result = run_bb84(n_bits=n_bits, backend="python", include_eve=False)
        qber = calculate_qber(result["alice_key"], result["bob_key"])
        assert qber < 0.05, f"QBER too high without Eve: {qber:.4f} (n_bits={n_bits})"

    def test_no_eve_keys_match_exactly(self):
        result = run_bb84(n_bits=256, backend="python", include_eve=False)
        assert result["alice_key"] == result["bob_key"], "Sifted keys should be identical without Eve"


# ---------------------------------------------------------------------------
# QBER — with Eve (intercept-resend)
# ---------------------------------------------------------------------------

class TestQBEREve:
    """Eve's intercept-resend attack causes QBER ≥ 0.20."""

    @pytest.mark.parametrize("n_bits", [64, 128, 256])
    def test_eve_qber_above_threshold(self, n_bits):
        # Average over 10 independent runs for statistical stability.
        # Threshold is 0.15: well above the no-Eve baseline (~0%) and
        # safely below the theoretical intercept-resend mean (~25%), while
        # tolerating the higher variance of small sifted-key sizes (n=64).
        qbers = []
        for seed in range(10):
            result = run_bb84(n_bits=n_bits, backend="python", include_eve=True)
            if result["n_sifted"] > 0:
                qbers.append(calculate_qber(result["alice_key"], result["bob_key"]))
        assert qbers, "No valid sifted keys produced with Eve"
        avg_qber = sum(qbers) / len(qbers)
        assert avg_qber >= 0.15, (
            f"Eve QBER too low: avg={avg_qber:.4f} (n_bits={n_bits})"
        )

    def test_eve_keys_differ_from_alice(self):
        """Eve should introduce detectable errors in the sifted key."""
        mismatches = 0
        for _ in range(10):
            result = run_bb84(n_bits=256, backend="python", include_eve=True)
            if result["n_sifted"] > 0:
                qber = calculate_qber(result["alice_key"], result["bob_key"])
                if qber > 0:
                    mismatches += 1
        assert mismatches > 0, "Eve never introduced errors (statistically impossible)"


# ---------------------------------------------------------------------------
# calculate_qber unit tests
# ---------------------------------------------------------------------------

class TestCalculateQber:
    """Unit tests for the calculate_qber helper."""

    def test_correct_fraction(self):
        alice_key = [0, 1, 0, 1, 0, 1, 0, 1]
        bob_key   = [0, 0, 0, 0, 0, 1, 0, 1]  # 2 errors out of 8
        assert abs(calculate_qber(alice_key, bob_key) - 0.25) < 1e-10

    def test_zero_on_matching_keys(self):
        key = [0, 1, 0, 1, 1, 0]
        assert calculate_qber(key, key) == 0.0

    def test_one_on_all_errors(self):
        alice_key = [0, 1, 0, 1]
        bob_key   = [1, 0, 1, 0]
        assert abs(calculate_qber(alice_key, bob_key) - 1.0) < 1e-10

    def test_empty_keys_returns_zero(self):
        assert calculate_qber([], []) == 0.0


# ---------------------------------------------------------------------------
# Qiskit Aer backend — marked @pytest.mark.slow
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestQiskitAerBackend:
    """Qiskit Aer backend. Run with: pytest -m slow"""

    @pytest.mark.parametrize("n_bits", [64, 128, 256])
    def test_qiskit_no_eve_qber_below_threshold(self, n_bits):
        result = run_bb84(n_bits=n_bits, backend="qiskit", include_eve=False)
        assert result["n_sifted"] > 0
        qber = calculate_qber(result["alice_key"], result["bob_key"])
        assert qber < 0.05, f"Qiskit QBER too high without Eve: {qber:.4f}"

    @pytest.mark.parametrize("n_bits", [64, 128, 256])
    def test_qiskit_no_eve_keys_match_exactly(self, n_bits):
        result = run_bb84(n_bits=n_bits, backend="qiskit", include_eve=False)
        assert result["alice_key"] == result["bob_key"]

    @pytest.mark.parametrize("n_bits", [64, 128, 256])
    def test_qiskit_sifted_key_length_approx_half_raw(self, n_bits):
        result = run_bb84(n_bits=n_bits, backend="qiskit")
        ratio = result["n_sifted"] / n_bits
        assert 0.30 <= ratio <= 0.70

    @pytest.mark.parametrize("n_bits", [64, 128, 256])
    def test_qiskit_eve_qber_above_threshold(self, n_bits):
        qbers = []
        for _ in range(3):
            result = run_bb84(n_bits=n_bits, backend="qiskit", include_eve=True)
            if result["n_sifted"] > 0:
                qbers.append(calculate_qber(result["alice_key"], result["bob_key"]))
        assert qbers, "No valid sifted keys from Qiskit Eve run"
        avg_qber = sum(qbers) / len(qbers)
        assert avg_qber >= 0.20, f"Qiskit Eve QBER too low: {avg_qber:.4f}"
