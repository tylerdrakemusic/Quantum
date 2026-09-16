from __future__ import annotations

import json

from time_crystal import (
    EvidenceBundle,
    FloquetIsingProtocol,
    NoiseConfig,
    ValidationStatus,
    run_floquet_ising,
    run_noisy_floquet_ising,
)


def _protocol(**overrides: object) -> FloquetIsingProtocol:
    values: dict[str, object] = {
        "system_size": 3,
        "periods": 16,
        "repetitions": 32,
        "pulse_angle": 3.141592653589793,
        "interaction_strength": 0.15,
        "disorder_strength": 0.0,
    }
    values.update(overrides)
    return FloquetIsingProtocol(**values)


def test_noisy_run_replays_with_typed_provenance_and_separate_source() -> None:
    noise = NoiseConfig(depolarizing_probability=0.08, readout_flip_probability=0.03)

    first = run_noisy_floquet_ising(_protocol(), seed=41, noise=noise)
    second = run_noisy_floquet_ising(_protocol(), seed=41, noise=noise)

    assert first == second
    assert first.provenance.source == "aer_noisy_simulation"
    assert first.provenance.evidence_schema_version == "v2"
    assert first.provenance.simulator == "local_aer_style"
    assert first.noise == noise
    assert first.diagnostics.noise_dominance is not None
    assert first.diagnostics.lifetime is not None


def test_depolarizing_evolution_is_distinct_from_readout_noise() -> None:
    depolarizing_only = run_noisy_floquet_ising(
        _protocol(pulse_angle=0.0),
        seed=19,
        noise=NoiseConfig(depolarizing_probability=1.0, readout_flip_probability=0.0),
    )
    readout_only = run_noisy_floquet_ising(
        _protocol(pulse_angle=0.0),
        seed=19,
        noise=NoiseConfig(depolarizing_probability=0.0, readout_flip_probability=1.0),
    )

    assert depolarizing_only.response_trace != readout_only.response_trace
    assert depolarizing_only.reproducibility["evolution_noise"] == "depolarizing_pauli_channel"
    assert depolarizing_only.reproducibility["measurement_noise"] == "readout_bit_flip"
    assert depolarizing_only.noise.digest != readout_only.noise.digest


def test_noisy_v2_round_trip_and_v1_ideal_read_are_compatible() -> None:
    noisy = run_noisy_floquet_ising(
        _protocol(periods=8),
        seed=7,
        noise=NoiseConfig(depolarizing_probability=0.04, readout_flip_probability=0.02),
    )

    encoded = noisy.to_json()
    restored = EvidenceBundle.from_json(encoded)

    assert json.loads(encoded)["schema_version"] == "v2"
    assert restored == noisy
    assert EvidenceBundle.from_json(run_floquet_ising(_protocol(), seed=7).to_json()).provenance.source == (
        "local_ideal_simulation"
    )


def test_failed_controls_are_inconclusive_and_finite_size_false_positive_is_not_supported() -> None:
    result = run_noisy_floquet_ising(
        _protocol(system_size=2, periods=4),
        seed=7,
        noise=NoiseConfig(depolarizing_probability=0.9, readout_flip_probability=0.9),
    )

    assert result.status in (ValidationStatus.INCONCLUSIVE, ValidationStatus.INVALID)
    assert result.status is not ValidationStatus.SUPPORTED
    assert result.diagnostics.finite_size_false_positive.status in {"inconclusive", "fail"}
    assert result.diagnostics.baseline_response.status in {"pass", "fail", "inconclusive"}
