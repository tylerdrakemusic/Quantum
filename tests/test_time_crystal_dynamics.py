from __future__ import annotations

import json

import pytest

from time_crystal import (
    EvidenceBundle,
    EvidenceUnavailable,
    ProtocolValidationError,
    UnsupportedSchemaVersion,
    ValidationStatus,
    run_floquet_ising,
)
from time_crystal.protocol import FloquetIsingProtocol


def _protocol(**overrides: object) -> FloquetIsingProtocol:
    values: dict[str, object] = {
        "system_size": 3,
        "periods": 16,
        "repetitions": 1,
        "pulse_angle": 3.141592653589793,
        "interaction_strength": 0.15,
        "disorder_strength": 0.0,
        "observable": "magnetization_z",
    }
    values.update(overrides)
    return FloquetIsingProtocol(**values)


def test_malformed_protocols_are_rejected_deterministically() -> None:
    with pytest.raises(ProtocolValidationError, match="system_size"):
        _protocol(system_size=1)

    with pytest.raises(ProtocolValidationError, match="periods"):
        _protocol(periods=0)


def test_seeded_ideal_replay_is_identical_and_does_not_use_randomness_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("live randomness must not be consulted")

    monkeypatch.setattr("quantum_rt.random_bits", fail_if_called, raising=False)

    first = run_floquet_ising(_protocol(disorder_strength=0.2), seed=41)
    second = run_floquet_ising(_protocol(disorder_strength=0.2), seed=41)

    assert first == second
    assert first.provenance.seed == 41
    assert first.provenance.source == "local_ideal_simulation"
    assert first.provenance.protocol_digest
    assert first.provenance.capability_version
    assert first.provenance.evidence_schema_version == "v1"
    assert first.reproducibility["seed_policy"] == "explicit_local_seed"


def test_validator_reports_independent_subharmonic_and_evidence_diagnostics() -> None:
    result = run_floquet_ising(_protocol(), seed=7)

    assert result.status is ValidationStatus.CANDIDATE
    assert result.diagnostics.subharmonic_response.status == "pass"
    assert result.diagnostics.evidence_limitations.status == "insufficient_controls"
    assert result.response_trace.periods == 16
    assert len(result.response_trace.values) == 16


def test_insufficient_evidence_is_inconclusive_even_with_an_alternating_fixture() -> None:
    result = run_floquet_ising(_protocol(periods=4), seed=7)

    assert result.status is ValidationStatus.INCONCLUSIVE
    assert result.diagnostics.subharmonic_response.status == "pass"
    assert "insufficient_time_window" in result.failure_modes


def test_non_alternating_fixture_is_not_a_candidate() -> None:
    result = run_floquet_ising(_protocol(pulse_angle=0.0), seed=7)

    assert result.status is ValidationStatus.INCONCLUSIVE
    assert result.diagnostics.subharmonic_response.status == "fail"


def test_unavailable_evidence_is_explicit_and_not_fabricated() -> None:
    bundle = EvidenceBundle.unavailable(
        reason="local simulator unavailable",
        source="local_ideal_simulation",
    )

    assert bundle.status is ValidationStatus.UNAVAILABLE
    assert isinstance(bundle.evidence, EvidenceUnavailable)
    assert bundle.evidence.reason == "local simulator unavailable"
    assert bundle.response_trace is None


def test_versioned_json_evidence_round_trip_preserves_numbers_and_provenance() -> None:
    original = run_floquet_ising(_protocol(), seed=11)
    encoded = original.to_json()
    restored = EvidenceBundle.from_json(encoded)

    assert json.loads(encoded)["schema_version"] == "v1"
    assert restored == original
    assert restored.response_trace.values == original.response_trace.values
    assert restored.provenance.protocol_digest == original.provenance.protocol_digest


def test_unsupported_evidence_schema_version_is_rejected() -> None:
    payload = json.loads(run_floquet_ising(_protocol(), seed=11).to_json())
    payload["schema_version"] = "v999"

    with pytest.raises(UnsupportedSchemaVersion, match="v999"):
        EvidenceBundle.from_json(json.dumps(payload))


def test_package_isolation_exposes_no_existing_runtime_or_hardware_adapters() -> None:
    import time_crystal

    assert not hasattr(time_crystal, "quantum_rt")
    assert not hasattr(time_crystal, "quantum_backend")
    assert not hasattr(time_crystal, "Aer")