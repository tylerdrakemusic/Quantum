from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from .dynamics import run_floquet_ising, run_noisy_floquet_ising
from .evidence import EvidenceBundle
from .protocol import FloquetIsingProtocol, NoiseConfig, Provenance, ValidationStatus


class ComparativeClassification(str, Enum):
    SUPPORTED = "supported"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class Perturbation:
    kind: str
    value: float | int | None = None

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("perturbation kind must not be empty")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float, type(None))):
            raise ValueError("perturbation value must be numeric or None")


@dataclass(frozen=True)
class ComparativeRequest:
    protocol: FloquetIsingProtocol
    noise_models: tuple[NoiseConfig, ...]
    perturbations: tuple[Perturbation, ...]
    system_sizes: tuple[int, ...]
    seed: int
    max_cases: int
    stable_pulse_boundaries: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("seed must be a non-negative integer")
        if isinstance(self.max_cases, bool) or not isinstance(self.max_cases, int) or self.max_cases < 1:
            raise ValueError("max_cases must be positive")
        if not self.noise_models or not self.perturbations or not self.system_sizes:
            raise ValueError("noise_models, perturbations, and system_sizes must not be empty")


@dataclass(frozen=True)
class ComparativeCase:
    protocol: FloquetIsingProtocol | None
    noise: NoiseConfig
    perturbation: Perturbation
    classification: ComparativeClassification
    evidence: EvidenceBundle
    diagnostics: dict[str, Any]

    @property
    def digest(self) -> str:
        payload = {
            "protocol_digest": None if self.protocol is None else self.protocol.digest,
            "noise_digest": self.noise.digest,
            "perturbation": {"kind": self.perturbation.kind, "value": self.perturbation.value},
            "classification": self.classification.value,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ComparativeMatrix:
    cases: tuple[ComparativeCase, ...]
    declared_case_count: int
    max_cases: int
    provenance: dict[str, Any]

    @property
    def case_count(self) -> int:
        return len(self.cases)


def run_comparative_matrix(request: ComparativeRequest) -> ComparativeMatrix:
    declared = len(request.noise_models) * len(request.perturbations) * len(request.system_sizes)
    cases: list[ComparativeCase] = []
    for noise in request.noise_models:
        for perturbation in request.perturbations:
            for system_size in request.system_sizes:
                if len(cases) >= request.max_cases:
                    break
                case = _run_case(request, noise, perturbation, system_size)
                cases.append(case)
            if len(cases) >= request.max_cases:
                break
        if len(cases) >= request.max_cases:
            break
    return ComparativeMatrix(
        cases=tuple(cases),
        declared_case_count=declared,
        max_cases=request.max_cases,
        provenance={
            "source": "in_memory_comparative_matrix",
            "seed": request.seed,
            "seed_policy": "explicit_case_seed",
            "case_order": "noise_model,perturbation,system_size",
            "stable_pulse_boundaries": request.stable_pulse_boundaries,
        },
    )


def _run_case(
    request: ComparativeRequest,
    noise: NoiseConfig,
    perturbation: Perturbation,
    system_size: int,
) -> ComparativeCase:
    if system_size < 2 or system_size > 10:
        return _unavailable_case(
            None,
            noise,
            perturbation,
            ComparativeClassification.INVALID,
            "system size is outside the feasible bounded ladder 2 through 10",
            protocol_digest=_protocol_digest_for_size(request.protocol, system_size),
            system_size=system_size,
            seed=request.seed,
        )
    protocol = FloquetIsingProtocol(
        system_size=system_size,
        periods=request.protocol.periods,
        repetitions=request.protocol.repetitions,
        pulse_angle=request.protocol.pulse_angle + (float(perturbation.value or 0.0) if perturbation.kind == "pulse_angle_detuning" else 0.0),
        interaction_strength=request.protocol.interaction_strength,
        disorder_strength=request.protocol.disorder_strength,
        observable=request.protocol.observable,
    )
    if perturbation.kind == "pulse_order_disruption" and not request.stable_pulse_boundaries:
        return _unavailable_case(
            protocol,
            noise,
            perturbation,
            ComparativeClassification.UNSUPPORTED,
            "pulse-order disruption requires stable pulse boundaries",
            protocol_digest=protocol.digest,
            system_size=system_size,
            seed=request.seed,
        )
    if perturbation.kind not in {"none", "pulse_order_disruption", "pulse_angle_detuning"}:
        return _unavailable_case(
            protocol,
            noise,
            perturbation,
            ComparativeClassification.UNSUPPORTED,
            "perturbation is unavailable",
            protocol_digest=protocol.digest,
            system_size=system_size,
            seed=request.seed,
        )
    if noise == NoiseConfig():
        evidence = run_floquet_ising(
            protocol,
            seed=request.seed,
            pulse_order_disrupted=perturbation.kind == "pulse_order_disruption",
        )
    else:
        evidence = run_noisy_floquet_ising(
            protocol,
            seed=request.seed,
            noise=noise,
            pulse_order_disrupted=perturbation.kind == "pulse_order_disruption",
        )
    evidence = replace(
        evidence,
        reproducibility={
            **evidence.reproducibility,
            "comparative_perturbation": perturbation.kind,
            "comparative_perturbation_value": perturbation.value,
            "pulse_order_boundaries": request.stable_pulse_boundaries,
        },
    )
    classification = _classify(evidence)
    return ComparativeCase(
        protocol,
        noise,
        perturbation,
        classification,
        evidence,
        {
            "evidence_status": evidence.status.value,
            "protocol_digest": protocol.digest,
            "noise_digest": noise.digest,
            "reason": None if evidence.evidence is None else evidence.evidence.reason,
        },
    )


def _classify(evidence: EvidenceBundle) -> ComparativeClassification:
    if evidence.status is ValidationStatus.UNAVAILABLE:
        return ComparativeClassification.UNSUPPORTED
    if evidence.status is ValidationStatus.INVALID:
        return ComparativeClassification.INVALID
    if evidence.diagnostics is not None and evidence.diagnostics.subharmonic_response.status == "fail":
        return ComparativeClassification.REJECTED
    if evidence.status is ValidationStatus.INCONCLUSIVE:
        return ComparativeClassification.INCONCLUSIVE
    if evidence.status is ValidationStatus.CANDIDATE or evidence.status is ValidationStatus.SUPPORTED:
        return ComparativeClassification.SUPPORTED
    return ComparativeClassification.REJECTED


def _unavailable_case(
    protocol: FloquetIsingProtocol | None,
    noise: NoiseConfig,
    perturbation: Perturbation,
    classification: ComparativeClassification,
    reason: str,
    *,
    protocol_digest: str,
    system_size: int,
    seed: int,
) -> ComparativeCase:
    unavailable = EvidenceBundle.unavailable(reason=reason, source="in_memory_comparative_matrix")
    evidence = replace(
        unavailable,
        provenance=Provenance(
            unavailable.provenance.capability_version,
            unavailable.provenance.evidence_schema_version,
            protocol_digest,
            unavailable.provenance.source,
            seed,
            unavailable.provenance.simulator,
            noise.digest,
        ),
        reproducibility={
            "seed_policy": "explicit_case_seed",
            "comparative_perturbation": perturbation.kind,
            "comparative_perturbation_value": perturbation.value,
            "system_size": system_size,
        },
    )
    return ComparativeCase(
        protocol,
        noise,
        perturbation,
        classification,
        evidence,
        {
            "reason": reason,
            "system_size": system_size,
            "protocol_digest": protocol_digest,
            "noise_digest": noise.digest,
        },
    )


def _protocol_digest_for_size(protocol: FloquetIsingProtocol, system_size: int) -> str:
    payload = protocol.as_dict()
    payload["system_size"] = system_size
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()