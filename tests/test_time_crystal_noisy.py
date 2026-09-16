from __future__ import annotations

import json
import math

import pytest

from time_crystal import (
    EvidenceBundle,
    FloquetIsingProtocol,
    NoiseConfig,
    ValidationStatus,
    run_floquet_ising,
    run_noisy_floquet_ising,
    ProtocolValidationError,
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


def test_coherent_over_rotation_offset_defaults_to_zero_and_validates_bounds() -> None:
    assert NoiseConfig().coherent_pulse_angle_offset == 0.0
    assert NoiseConfig(coherent_pulse_angle_offset=-math.pi / 2).coherent_pulse_angle_offset == -math.pi / 2
    assert NoiseConfig(coherent_pulse_angle_offset=math.pi / 2).coherent_pulse_angle_offset == math.pi / 2

    for value in (float("nan"), float("inf"), -math.pi / 2 - 0.01, math.pi / 2 + 0.01):
        with pytest.raises(ProtocolValidationError, match="coherent_pulse_angle_offset"):
            NoiseConfig(coherent_pulse_angle_offset=value)


def test_zero_offset_preserves_existing_noisy_trace() -> None:
    noise = NoiseConfig(depolarizing_probability=0.08, readout_flip_probability=0.03)

    implicit = run_noisy_floquet_ising(_protocol(), seed=41, noise=noise)
    explicit = run_noisy_floquet_ising(
        _protocol(), seed=41, noise=NoiseConfig(0.08, 0.03, coherent_pulse_angle_offset=0.0)
    )

    assert explicit.response_trace == implicit.response_trace
    assert explicit.noise.digest == implicit.noise.digest


def test_nonzero_offset_changes_every_pulse_and_is_deterministic() -> None:
    noise = NoiseConfig(coherent_pulse_angle_offset=0.12)

    first = run_noisy_floquet_ising(_protocol(pulse_angle=0.8, periods=8), seed=41, noise=noise)
    second = run_noisy_floquet_ising(_protocol(pulse_angle=0.8, periods=8), seed=41, noise=noise)
    ideal = run_noisy_floquet_ising(_protocol(pulse_angle=0.8, periods=8), seed=41, noise=NoiseConfig())

    assert first == second
    assert first.response_trace != ideal.response_trace
    assert first.reproducibility["coherent_noise"] == "constant_pulse_angle_offset"
    assert first.reproducibility["coherent_pulse_angle_offset_radians"] == 0.12


def test_coherent_offset_composes_with_depolarizing_and_readout_noise() -> None:
    coherent = NoiseConfig(coherent_pulse_angle_offset=0.12)
    composed = NoiseConfig(0.08, 0.03, coherent_pulse_angle_offset=0.12)

    coherent_result = run_noisy_floquet_ising(_protocol(), seed=41, noise=coherent)
    composed_result = run_noisy_floquet_ising(_protocol(), seed=41, noise=composed)

    assert composed_result.response_trace != coherent_result.response_trace
    assert composed_result.noise.digest != coherent_result.noise.digest
    assert composed_result.reproducibility["evolution_noise"] == "coherent_pulse_angle_offset_then_depolarizing_pauli_channel"
    assert composed_result.reproducibility["measurement_noise"] == "readout_bit_flip"


def test_coherent_noise_is_attributed_in_provenance_and_digest_inputs() -> None:
    zero = NoiseConfig()
    offset = NoiseConfig(coherent_pulse_angle_offset=0.12)

    assert offset.digest != zero.digest
    assert offset.as_dict()["coherent_pulse_angle_offset"] == 0.12
    result = run_noisy_floquet_ising(_protocol(), seed=41, noise=offset)
    assert result.provenance.noise_config_digest == offset.digest
    assert result.diagnostics.noise_dominance.metadata["noise_digest"] == offset.digest
