from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProtocolValidationError(ValueError):
    pass


class ValidationStatus(str, Enum):
    CANDIDATE = "candidate"
    SUPPORTED = "supported"
    INCONCLUSIVE = "inconclusive"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class FloquetIsingProtocol:
    system_size: int
    periods: int
    repetitions: int
    pulse_angle: float
    interaction_strength: float
    disorder_strength: float
    observable: str = "magnetization_z"

    def __post_init__(self) -> None:
        if isinstance(self.system_size, bool) or not 2 <= self.system_size <= 10:
            raise ProtocolValidationError("system_size must be an integer from 2 through 10")
        if isinstance(self.periods, bool) or not 1 <= self.periods <= 4096:
            raise ProtocolValidationError("periods must be an integer from 1 through 4096")
        if isinstance(self.repetitions, bool) or not 1 <= self.repetitions <= 4096:
            raise ProtocolValidationError("repetitions must be an integer from 1 through 4096")
        for name, value in (
            ("pulse_angle", self.pulse_angle),
            ("interaction_strength", self.interaction_strength),
            ("disorder_strength", self.disorder_strength),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ProtocolValidationError(f"{name} must be a finite number")
        if not 0.0 <= self.disorder_strength <= 1.0:
            raise ProtocolValidationError("disorder_strength must be between 0 and 1")
        if self.observable != "magnetization_z":
            raise ProtocolValidationError("observable must be magnetization_z")

    def as_dict(self) -> dict[str, Any]:
        return {
            "system_size": self.system_size,
            "periods": self.periods,
            "repetitions": self.repetitions,
            "pulse_angle": self.pulse_angle,
            "interaction_strength": self.interaction_strength,
            "disorder_strength": self.disorder_strength,
            "observable": self.observable,
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class NoiseConfig:
    depolarizing_probability: float = 0.0
    readout_flip_probability: float = 0.0
    model_version: str = "depolarizing_readout_coherent_over_rotation_v2"
    coherent_pulse_angle_offset: float = 0.0

    def __post_init__(self) -> None:
        if self.model_version not in {
            "depolarizing_readout_v1",
            "depolarizing_readout_coherent_over_rotation_v2",
        }:
            raise ProtocolValidationError("model_version must be a supported noise model version")
        for name, value in (
            ("depolarizing_probability", self.depolarizing_probability),
            ("readout_flip_probability", self.readout_flip_probability),
            ("coherent_pulse_angle_offset", self.coherent_pulse_angle_offset),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ProtocolValidationError(f"{name} must be a finite number")
            if name == "coherent_pulse_angle_offset":
                if not -math.pi / 2 <= value <= math.pi / 2:
                    raise ProtocolValidationError(f"{name} must be between -pi/2 and pi/2")
            elif not 0.0 <= value <= 1.0:
                raise ProtocolValidationError(f"{name} must be between 0 and 1")
        if self.model_version == "depolarizing_readout_v1" and self.coherent_pulse_angle_offset != 0.0:
            raise ProtocolValidationError("v1 noise artifacts cannot represent a coherent pulse angle offset")

    def as_dict(self) -> dict[str, Any]:
        return {
            "depolarizing_probability": self.depolarizing_probability,
            "readout_flip_probability": self.readout_flip_probability,
            "coherent_pulse_angle_offset": self.coherent_pulse_angle_offset,
            "model_version": self.model_version,
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


VALID_INITIAL_STATES = ("all_zero", "all_one", "alternating")


@dataclass(frozen=True)
class Provenance:
    capability_version: str
    evidence_schema_version: str
    protocol_digest: str
    source: str
    seed: int | None
    simulator: str = "python_statevector"
    noise_config_digest: str | None = None


@dataclass(frozen=True)
class ResponseTrace:
    periods: int
    values: tuple[float, ...]
    uncertainties: tuple[float, ...] = ()
    shots_per_period: int = 1

    @property
    def means(self) -> tuple[float, ...]:
        return self.values


@dataclass(frozen=True)
class Diagnostic:
    status: str
    metric: float | None
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Diagnostics:
    subharmonic_response: Diagnostic
    evidence_limitations: Diagnostic
    spectral_half_frequency: Diagnostic | None = None
    shuffled_null: Diagnostic | None = None
    lifetime: Diagnostic | None = None
    non_period_doubled_control: Diagnostic | None = None
    baseline_response: Diagnostic | None = None
    noise_dominance: Diagnostic | None = None
    finite_size_false_positive: Diagnostic | None = None


@dataclass(frozen=True)
class EvidenceUnavailable:
    reason: str
    source: str