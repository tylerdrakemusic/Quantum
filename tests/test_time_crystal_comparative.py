from __future__ import annotations

from time_crystal import (
    ComparativeClassification,
    ComparativeRequest,
    NoiseConfig,
    Perturbation,
    run_comparative_matrix,
)
from time_crystal.protocol import FloquetIsingProtocol


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


def test_comparative_matrix_replays_and_preserves_supported_evidence() -> None:
    request = ComparativeRequest(
        protocol=_protocol(),
        noise_models=(NoiseConfig(), NoiseConfig(depolarizing_probability=0.05)),
        perturbations=(Perturbation("none"), Perturbation("pulse_order_disruption", 1)),
        system_sizes=(3, 4),
        seed=23,
        max_cases=6,
        stable_pulse_boundaries=True,
    )

    first = run_comparative_matrix(request)
    second = run_comparative_matrix(request)

    assert first == second
    assert first.case_count == 6
    assert all(case.classification in set(ComparativeClassification) for case in first.cases)
    supported = [case for case in first.cases if case.classification is ComparativeClassification.SUPPORTED]
    assert supported
    assert all(case.evidence.provenance.protocol_digest == case.protocol.digest for case in supported)
    assert all(case.evidence.reproducibility["seed_policy"] == "explicit_local_seed" for case in supported)
    pulse_order = [case for case in first.cases if case.perturbation.kind == "pulse_order_disruption"]
    assert pulse_order
    assert all(case.classification is not ComparativeClassification.UNSUPPORTED for case in pulse_order)
    order_matrix = run_comparative_matrix(
        ComparativeRequest(
            protocol=_protocol(pulse_angle=2.8, repetitions=256),
            noise_models=(NoiseConfig(),),
            perturbations=(Perturbation("none"), Perturbation("pulse_order_disruption")),
            system_sizes=(3,),
            seed=23,
            max_cases=2,
            stable_pulse_boundaries=True,
        )
    )
    baseline, disrupted = order_matrix.cases
    assert disrupted.evidence.reproducibility["comparative_perturbation"] == "pulse_order_disruption"
    assert disrupted.digest != baseline.digest
    assert first.provenance["case_order"]


def test_comparative_matrix_reports_unsupported_mechanisms_without_fabricating_evidence() -> None:
    request = ComparativeRequest(
        protocol=_protocol(),
        noise_models=(NoiseConfig(leakage_probability=0.2),),
        perturbations=(Perturbation("none"),),
        system_sizes=(3,),
        seed=23,
        max_cases=2,
    )

    result = run_comparative_matrix(request)

    assert result.case_count == 1
    case = result.cases[0]
    assert case.classification is ComparativeClassification.UNSUPPORTED
    assert case.evidence.response_trace is None
    assert case.evidence.evidence is not None
    assert case.evidence.provenance.noise_config_digest == request.noise_models[0].digest
    assert case.diagnostics["reason"]


def test_comparative_matrix_types_boundary_and_size_failures() -> None:
    result = run_comparative_matrix(
        ComparativeRequest(
            protocol=_protocol(),
            noise_models=(NoiseConfig(),),
            perturbations=(Perturbation("pulse_order_disruption"),),
            system_sizes=(1, 11),
            seed=23,
            max_cases=2,
        )
    )
    boundary_result = run_comparative_matrix(
        ComparativeRequest(
            protocol=_protocol(),
            noise_models=(NoiseConfig(),),
            perturbations=(Perturbation("pulse_order_disruption"),),
            system_sizes=(3,),
            seed=23,
            max_cases=1,
        )
    )

    assert {case.classification for case in result.cases} == {ComparativeClassification.INVALID}
    assert boundary_result.cases[0].classification is ComparativeClassification.UNSUPPORTED
    assert boundary_result.cases[0].evidence.response_trace is None


def test_comparative_matrix_rejects_a_non_subharmonic_result() -> None:
    result = run_comparative_matrix(
        ComparativeRequest(
            protocol=_protocol(pulse_angle=0.0),
            noise_models=(NoiseConfig(),),
            perturbations=(Perturbation("none"),),
            system_sizes=(3,),
            seed=23,
            max_cases=1,
        )
    )

    assert result.cases[0].classification is ComparativeClassification.REJECTED
