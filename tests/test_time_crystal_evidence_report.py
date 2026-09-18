from __future__ import annotations

import json

import pytest

from time_crystal import (
    ComparativeClassification,
    ComparativeRequest,
    EvidenceReport,
    NoiseConfig,
    Perturbation,
    ReplayValidationError,
    build_evidence_report,
    replay_evidence_report,
    run_comparative_matrix,
)
from time_crystal.protocol import FloquetIsingProtocol
from time_crystal.evidence_report import MAX_REPORT_BYTES


def _protocol(**overrides: object) -> FloquetIsingProtocol:
    values: dict[str, object] = {
        "system_size": 3,
        "periods": 8,
        "repetitions": 4,
        "pulse_angle": 3.141592653589793,
        "interaction_strength": 0.15,
        "disorder_strength": 0.1,
    }
    values.update(overrides)
    return FloquetIsingProtocol(**values)


def _request(**overrides: object) -> ComparativeRequest:
    values: dict[str, object] = {
        "protocol": _protocol(),
        "noise_models": (NoiseConfig(), NoiseConfig(depolarizing_probability=0.05)),
        "perturbations": (Perturbation("none"), Perturbation("pulse_order_disruption")),
        "system_sizes": (3,),
        "seed": 23,
        "max_cases": 4,
        "stable_pulse_boundaries": True,
    }
    values.update(overrides)
    return ComparativeRequest(**values)


def test_report_contains_case_identity_classification_and_unavailable_details() -> None:
    request = _request(
        noise_models=(NoiseConfig(leakage_probability=0.2),),
        perturbations=(Perturbation("none"),),
    )
    report = build_evidence_report(request, run_comparative_matrix(request))

    assert report.schema_version == "v1"
    assert report.request.protocol.digest == request.protocol.digest
    assert report.cases[0].classification is ComparativeClassification.UNSUPPORTED
    serialized_case = report.to_dict()["cases"][0]
    assert serialized_case["protocol_digest"] == request.protocol.digest
    assert serialized_case["noise_digest"] == request.noise_models[0].digest
    assert serialized_case["unavailable"] == {
        "reason": "local simulator has no explicit out-of-subspace state representation for leakage",
        "source": "aer_noisy_simulation",
    }
    assert report.cases[0].evidence is not None
    assert report.provenance["case_order"] == "noise_model,perturbation,system_size"


def test_report_round_trip_is_lossless_and_json_is_deterministic() -> None:
    request = _request(protocol=_protocol(pulse_angle=0.12345678901234567))
    matrix = run_comparative_matrix(request)
    report = build_evidence_report(request, matrix)

    encoded = report.to_json()

    assert encoded == report.to_json()
    assert EvidenceReport.from_json(encoded) == report
    assert json.loads(encoded)["schema_version"] == "v1"
    assert json.loads(encoded)["request"]["protocol"]["pulse_angle"] == 0.12345678901234567


def test_report_preserves_supported_rejected_inconclusive_invalid_and_unsupported_cases() -> None:
    requests = (
        _request(),
        _request(protocol=_protocol(pulse_angle=0.0), noise_models=(NoiseConfig(),), perturbations=(Perturbation("none"),)),
        _request(protocol=_protocol(periods=1, repetitions=1), noise_models=(NoiseConfig(),), perturbations=(Perturbation("none"),)),
        _request(system_sizes=(1,), noise_models=(NoiseConfig(),), perturbations=(Perturbation("none"),)),
        _request(noise_models=(NoiseConfig(leakage_probability=0.2),), perturbations=(Perturbation("none"),)),
    )
    classifications = {
        build_evidence_report(request, run_comparative_matrix(request)).cases[0].classification
        for request in requests
    }

    assert classifications == set(ComparativeClassification)


def test_replay_accepts_matching_request_and_detects_input_case_and_evidence_mismatches() -> None:
    request = _request()
    report = build_evidence_report(request, run_comparative_matrix(request))

    assert replay_evidence_report(report, request).matched

    with pytest.raises(ReplayValidationError, match="request digest"):
        replay_evidence_report(report, _request(seed=24))

    changed_cases = json.loads(report.to_json())
    changed_cases["cases"][0]["classification"] = "rejected"
    with pytest.raises(ReplayValidationError, match="classification"):
        replay_evidence_report(EvidenceReport.from_dict(changed_cases), request)

    changed_digest = json.loads(report.to_json())
    changed_digest["cases"][0]["case_digest"] = "0" * 64
    with pytest.raises(ReplayValidationError, match="case digest"):
        replay_evidence_report(EvidenceReport.from_dict(changed_digest), request)

    changed_evidence = json.loads(report.to_json())
    changed_evidence["cases"][0]["evidence"]["reproducibility"]["seed"] = 999
    with pytest.raises(ReplayValidationError, match="evidence"):
        replay_evidence_report(EvidenceReport.from_dict(changed_evidence), request)


def test_report_rejects_malformed_and_future_version_payloads_fail_closed() -> None:
    request = _request()
    payload = json.loads(build_evidence_report(request, run_comparative_matrix(request)).to_json())

    for malformed in ({}, {"schema_version": "v1"}, {**payload, "cases": "bad"}):
        with pytest.raises(ValueError):
            EvidenceReport.from_dict(malformed)

    payload["schema_version"] = "v999"
    with pytest.raises(ValueError, match="v999"):
        EvidenceReport.from_dict(payload)


def test_report_rejects_oversized_json_before_parsing() -> None:
    oversized_malformed_json = "{" + ("x" * MAX_REPORT_BYTES)

    with pytest.raises(ValueError, match="payload size limit"):
        EvidenceReport.from_json(oversized_malformed_json)


def test_report_rejects_empty_case_sets_during_deserialization() -> None:
    request = _request()
    payload = json.loads(build_evidence_report(request, run_comparative_matrix(request)).to_json())
    payload["cases"] = []
    payload["declared_case_count"] = 0

    with pytest.raises(ValueError, match="non-empty"):
        EvidenceReport.from_json(json.dumps(payload))