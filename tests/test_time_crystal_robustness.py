from __future__ import annotations

import json
from dataclasses import replace

from time_crystal import (
    ControlEvidence,
    RobustnessSweep,
    aggregate_evidence,
    run_mechanism_controls,
    run_robustness_sweep,
)
from time_crystal.robustness import RobustnessEvidence
from time_crystal.protocol import FloquetIsingProtocol


def _protocol(**overrides: object) -> FloquetIsingProtocol:
    values: dict[str, object] = {
        "system_size": 3,
        "periods": 8,
        "repetitions": 2,
        "pulse_angle": 3.141592653589793,
        "interaction_strength": 0.15,
        "disorder_strength": 0.1,
        "observable": "magnetization_z",
    }
    values.update(overrides)
    return FloquetIsingProtocol(**values)


def test_bounded_robustness_sweep_is_seed_replayable_with_per_case_evidence() -> None:
    sweep = RobustnessSweep(
        pulse_angle_detunings=(-0.1, 0.1),
        interaction_strengths=(0.1,),
        disorder_strengths=(0.0, 0.2),
        initial_states=("all_zero",),
        seeds=(5, 7),
        max_cases=4,
    )

    first = run_robustness_sweep(_protocol(), sweep)
    second = run_robustness_sweep(_protocol(), sweep)

    assert first == second
    assert first.status == "complete"
    assert first.case_count == 4
    assert len(first.cases) == 4
    assert all(case.evidence.provenance.seed in (5, 7) for case in first.cases)
    assert all(case.provenance["source"] == "local_ideal_simulation" for case in first.cases)
    assert first.provenance["max_cases"] == 4


def test_mechanism_controls_report_independent_diagnostics_and_provenance() -> None:
    controls = run_mechanism_controls(_protocol(), seed=13)

    assert isinstance(controls, ControlEvidence)
    assert set(controls.diagnostics) == {
        "no_disorder",
        "no_interaction",
        "pulse_angle_detuning",
        "phase_randomized_drive",
    }
    assert all(diagnostic.status in {"pass", "fail", "incomplete"} for diagnostic in controls.diagnostics.values())
    assert all(diagnostic.metadata["seed"] == 13 for diagnostic in controls.diagnostics.values())
    assert controls.provenance["source"] == "local_ideal_simulation"


def test_aggregation_keeps_v1_and_gates_failed_or_incomplete_required_evidence() -> None:
    baseline = run_robustness_sweep(
        _protocol(),
        RobustnessSweep(
            pulse_angle_detunings=(0.0,),
            interaction_strengths=(0.15,),
            disorder_strengths=(0.1,),
            initial_states=("all_zero",),
            seeds=(3,),
            max_cases=1,
        ),
    ).cases[0].evidence
    robustness = run_robustness_sweep(
        _protocol(),
        RobustnessSweep(
            pulse_angle_detunings=(0.0, 0.1),
            interaction_strengths=(0.15,),
            disorder_strengths=(0.1,),
            initial_states=("all_zero",),
            seeds=(3,),
            max_cases=1,
        ),
    )
    controls = run_mechanism_controls(_protocol(), seed=3)

    incomplete = replace(robustness, status="incomplete")
    assert isinstance(incomplete, RobustnessEvidence)
    aggregate = aggregate_evidence(baseline, robustness=incomplete, controls=controls)
    payload = json.loads(aggregate.to_json())

    assert aggregate.status.value == "inconclusive"
    assert "robustness_incomplete" in aggregate.failure_modes
    assert payload["schema_version"] == "v1"
    assert payload["robustness"]["case_count"] == 1
    assert payload["controls"]["status"] == "complete"