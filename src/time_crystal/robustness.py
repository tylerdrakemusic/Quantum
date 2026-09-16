from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from itertools import product
from typing import Any

from .dynamics import (
    _alternating_amplitude,
    _apply_interactions,
    _apply_rx,
    _basis_probabilities,
    _initial_state,
    _sample_magnetization,
    run_floquet_ising,
)
from .evidence import EvidenceBundle
from .protocol import FloquetIsingProtocol


@dataclass(frozen=True)
class RobustnessSweep:
    pulse_angle_detunings: tuple[float, ...]
    interaction_strengths: tuple[float, ...]
    disorder_strengths: tuple[float, ...]
    initial_states: tuple[str, ...]
    seeds: tuple[int, ...]
    max_cases: int

    def __post_init__(self) -> None:
        if self.max_cases < 1:
            raise ValueError("max_cases must be positive")
        if not all(isinstance(seed, int) and not isinstance(seed, bool) and seed >= 0 for seed in self.seeds):
            raise ValueError("seeds must contain non-negative integers")
        if not self.initial_states or any(state not in ("all_zero", "all_one", "alternating") for state in self.initial_states):
            raise ValueError("initial_states contains an unsupported state")

    @property
    def declared_case_count(self) -> int:
        return (
            len(self.pulse_angle_detunings)
            * len(self.interaction_strengths)
            * len(self.disorder_strengths)
            * len(self.initial_states)
            * len(self.seeds)
        )


@dataclass(frozen=True)
class RobustnessCase:
    pulse_angle_detuning: float
    interaction_strength: float
    disorder_strength: float
    initial_state: str
    seed: int
    evidence: EvidenceBundle

    @property
    def provenance(self) -> dict[str, Any]:
        return {
            "source": self.evidence.provenance.source,
            "seed": self.seed,
            "protocol_digest": self.evidence.provenance.protocol_digest,
            "case_digest": hashlib.sha256(
                json.dumps(
                    {
                        "pulse_angle_detuning": self.pulse_angle_detuning,
                        "interaction_strength": self.interaction_strength,
                        "disorder_strength": self.disorder_strength,
                        "initial_state": self.initial_state,
                        "seed": self.seed,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }


@dataclass(frozen=True)
class RobustnessEvidence:
    status: str
    cases: tuple[RobustnessCase, ...]
    declared_case_count: int
    max_cases: int
    provenance: dict[str, Any]

    @property
    def case_count(self) -> int:
        return len(self.cases)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "case_count": self.case_count,
            "declared_case_count": self.declared_case_count,
            "max_cases": self.max_cases,
            "provenance": self.provenance,
            "cases": [
                {
                    "pulse_angle_detuning": case.pulse_angle_detuning,
                    "interaction_strength": case.interaction_strength,
                    "disorder_strength": case.disorder_strength,
                    "initial_state": case.initial_state,
                    "seed": case.seed,
                    "provenance": case.provenance,
                    "evidence": case.evidence.to_dict(),
                }
                for case in self.cases
            ],
        }


@dataclass(frozen=True)
class ControlDiagnostic:
    status: str
    metric: float | None
    reason: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "metric": self.metric, "reason": self.reason, "metadata": self.metadata}


@dataclass(frozen=True)
class ControlEvidence:
    status: str
    diagnostics: dict[str, ControlDiagnostic]
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "diagnostics": {name: diagnostic.to_dict() for name, diagnostic in self.diagnostics.items()},
            "provenance": self.provenance,
        }


def run_robustness_sweep(protocol: FloquetIsingProtocol, sweep: RobustnessSweep) -> RobustnessEvidence:
    cases: list[RobustnessCase] = []
    combinations = product(
        sweep.pulse_angle_detunings,
        sweep.interaction_strengths,
        sweep.disorder_strengths,
        sweep.initial_states,
        sweep.seeds,
    )
    for pulse_detuning, interaction, disorder, initial_state, seed in combinations:
        if len(cases) >= sweep.max_cases:
            break
        case_protocol = FloquetIsingProtocol(
            system_size=protocol.system_size,
            periods=protocol.periods,
            repetitions=protocol.repetitions,
            pulse_angle=protocol.pulse_angle + pulse_detuning,
            interaction_strength=interaction,
            disorder_strength=disorder,
            observable=protocol.observable,
        )
        cases.append(
            RobustnessCase(
                pulse_detuning,
                interaction,
                disorder,
                initial_state,
                seed,
                run_floquet_ising(case_protocol, seed=seed, initial_state=initial_state),
            )
        )
    target_case_count = min(sweep.declared_case_count, sweep.max_cases)
    status = "complete" if len(cases) == target_case_count else "incomplete"
    return RobustnessEvidence(
        status=status,
        cases=tuple(cases),
        declared_case_count=sweep.declared_case_count,
        max_cases=sweep.max_cases,
        provenance={
            "source": "local_ideal_simulation",
            "seed_policy": "explicit_case_seed",
            "max_cases": sweep.max_cases,
            "declared_case_count": sweep.declared_case_count,
            "case_order": "pulse_angle_detuning,interaction_strength,disorder_strength,initial_state,seed",
        },
    )


def run_mechanism_controls(protocol: FloquetIsingProtocol, *, seed: int) -> ControlEvidence:
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    variants = {
        "no_disorder": (0.0, protocol.interaction_strength, protocol.pulse_angle),
        "no_interaction": (protocol.disorder_strength, 0.0, protocol.pulse_angle),
        "pulse_angle_detuning": (protocol.disorder_strength, protocol.interaction_strength, protocol.pulse_angle + 0.1),
    }
    diagnostics: dict[str, ControlDiagnostic] = {}
    for name, (disorder, interaction, pulse_angle) in variants.items():
        variant = FloquetIsingProtocol(
            system_size=protocol.system_size,
            periods=protocol.periods,
            repetitions=protocol.repetitions,
            pulse_angle=pulse_angle,
            interaction_strength=interaction,
            disorder_strength=disorder,
            observable=protocol.observable,
        )
        evidence = run_floquet_ising(variant, seed=seed)
        diagnostics[name] = _control_diagnostic(name, evidence.control_trace.values, seed)
    diagnostics["phase_randomized_drive"] = _phase_randomized_diagnostic(protocol, seed)
    return ControlEvidence(
        status="complete",
        diagnostics=diagnostics,
        provenance={"source": "local_ideal_simulation", "seed": seed, "seed_policy": "explicit_control_seed"},
    )


def aggregate_evidence(
    baseline: EvidenceBundle,
    *,
    robustness: RobustnessEvidence,
    controls: ControlEvidence,
) -> EvidenceBundle:
    failures = list(baseline.failure_modes)
    status = baseline.status
    if robustness.status == "unavailable" or controls.status == "unavailable":
        status = type(baseline.status).UNAVAILABLE
    elif robustness.status == "invalid" or controls.status == "invalid":
        status = type(baseline.status).INVALID
    else:
        if robustness.status != "complete":
            failures.append("robustness_incomplete")
        if controls.status != "complete" or any(item.status != "pass" for item in controls.diagnostics.values()):
            failures.append("controls_incomplete" if controls.status != "complete" else "controls_failed")
        if robustness.status != "complete" or controls.status != "complete" or any(
            item.status != "pass" for item in controls.diagnostics.values()
        ):
            status = type(baseline.status).INCONCLUSIVE
    return EvidenceBundle(
        status=status,
        provenance=baseline.provenance,
        response_trace=baseline.response_trace,
        diagnostics=baseline.diagnostics,
        failure_modes=tuple(dict.fromkeys(failures)),
        reproducibility=baseline.reproducibility,
        evidence=baseline.evidence,
        control_trace=baseline.control_trace,
        robustness=robustness.to_dict(),
        controls=controls.to_dict(),
    )


def _control_diagnostic(name: str, values: tuple[float, ...], seed: int) -> ControlDiagnostic:
    metric = _alternating_amplitude(values)
    return ControlDiagnostic(
        status="pass" if metric < 0.5 else "fail",
        metric=metric,
        reason=f"independent {name} control",
        metadata={"control": name, "seed": seed, "source": "local_ideal_simulation"},
    )


def _phase_randomized_diagnostic(protocol: FloquetIsingProtocol, seed: int) -> ControlDiagnostic:
    rng = random.Random(seed + 101)
    fields = tuple(rng.uniform(-protocol.disorder_strength, protocol.disorder_strength) for _ in range(protocol.system_size))
    state = _initial_state(protocol.system_size, "all_zero")
    values: list[float] = []
    for _ in range(protocol.periods):
        _apply_interactions(state, protocol, fields)
        angle = protocol.pulse_angle + rng.uniform(-0.25, 0.25)
        for qubit in range(protocol.system_size):
            _apply_rx(state, protocol.system_size, qubit, angle)
        probabilities = _basis_probabilities(state)
        samples = [_sample_magnetization(probabilities, protocol.system_size, rng) for _ in range(protocol.repetitions)]
        values.append(sum(samples) / len(samples))
    metric = _alternating_amplitude(tuple(values))
    return ControlDiagnostic(
        status="pass" if metric < 0.5 else "fail",
        metric=metric,
        reason="independent deterministic phase-randomized drive control",
        metadata={"control": "phase_randomized_drive", "seed": seed, "phase_seed": seed + 101, "source": "local_ideal_simulation"},
    )