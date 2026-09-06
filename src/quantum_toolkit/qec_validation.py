"""Seeded repetition-code validation with an intentionally bounded decoder."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import random
from pathlib import Path
from typing import Literal

from quantum_toolkit.benchmark_provenance import adapt_result
from quantum_toolkit.benchmark_replay import TOLERANCE_VERSION, replay_local

QEC_VALIDATION_VERSION = "2026-09-06.1"
_TOLERANCE_VERSION = TOLERANCE_VERSION
_ALLOWED_ROUNDS = (3, 5, 9)
_ALLOWED_RATES = (0.001, 0.005, 0.01)

DecoderStatus = Literal["clean", "corrected", "ambiguous", "uncorrectable", "malformed"]


@dataclass(frozen=True)
class QECValidationConfig:
    """Inputs for one reproducible repeated-round validation run."""

    seed: int
    distance: int
    rounds: int
    data_pauli_x_rate: float = 0.001
    syndrome_measurement_rate: float = 0.001
    logical_bit: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise ValueError("seed must be an integer")
        if not isinstance(self.distance, int) or isinstance(self.distance, bool) or self.distance < 3:
            raise ValueError("distance must be an integer >= 3")
        if self.distance % 2 == 0:
            raise ValueError("distance must be odd")
        if not isinstance(self.rounds, int) or isinstance(self.rounds, bool) or self.rounds < 1:
            raise ValueError("rounds must be a positive integer")
        for name, rate in (
            ("data_pauli_x_rate", self.data_pauli_x_rate),
            ("syndrome_measurement_rate", self.syndrome_measurement_rate),
        ):
            if not 0.0 <= rate <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.logical_bit not in (0, 1):
            raise ValueError("logical_bit must be 0 or 1")


@dataclass(frozen=True)
class DecoderResult:
    """Bounded decoder classification and optional correction."""

    status: DecoderStatus
    correction: tuple[int, ...]
    reason: str


def decode_repetition_syndrome(syndrome: tuple[int, ...], *, distance: int) -> DecoderResult:
    """Decode only clean or single-X syndromes, never guessing multi-faults."""
    if not isinstance(distance, int) or distance < 3 or distance % 2 == 0:
        raise ValueError("distance must be an odd integer >= 3")
    if len(syndrome) != distance - 1 or any(bit not in (0, 1) for bit in syndrome):
        return DecoderResult("malformed", (), "syndrome shape or values are invalid")
    if not any(syndrome):
        return DecoderResult("clean", (), "no syndrome detected")

    candidates = []
    for qubit in range(distance):
        expected = [0] * (distance - 1)
        if qubit > 0:
            expected[qubit - 1] = 1
        if qubit < distance - 1:
            expected[qubit] = 1
        if tuple(expected) == syndrome:
            candidates.append(qubit)
    if len(candidates) == 1:
        return DecoderResult("corrected", (candidates[0],), "single-X syndrome corrected")
    if sum(syndrome) <= 2:
        return DecoderResult("ambiguous", (), "syndrome is consistent with an unbounded multi-fault pattern")
    return DecoderResult("uncorrectable", (), "syndrome exceeds the bounded single-fault decoder")


def simulate_repeated_rounds(config: QECValidationConfig) -> dict[str, object]:
    """Simulate repeated noisy rounds and emit the normalized provenance contract."""
    rng = random.Random(config.seed)
    data_errors = [config.logical_bit] * config.distance
    syndrome_history: list[tuple[int, ...]] = []
    for _ in range(config.rounds):
        for qubit in range(config.distance):
            if rng.random() < config.data_pauli_x_rate:
                data_errors[qubit] ^= 1
        ideal = tuple(data_errors[index] ^ data_errors[index + 1] for index in range(config.distance - 1))
        observed = tuple(
            bit ^ int(rng.random() < config.syndrome_measurement_rate) for bit in ideal
        )
        syndrome_history.append(observed)

    majority_syndrome = tuple(
        int(sum(round_syndrome[index] for round_syndrome in syndrome_history) > config.rounds / 2)
        for index in range(config.distance - 1)
    )
    decoder = decode_repetition_syndrome(majority_syndrome, distance=config.distance)
    if decoder.status == "corrected":
        data_errors[decoder.correction[0]] ^= 1
    logical_outcome: int | None
    if decoder.status in {"clean", "corrected"}:
        logical_outcome = int(sum(data_errors) > config.distance / 2)
    else:
        logical_outcome = None
    logical_error = logical_outcome is not None and logical_outcome != config.logical_bit
    decoder_success = decoder.status in {"clean", "corrected"} and not logical_error
    result: dict[str, object] = {
        "validation_version": QEC_VALIDATION_VERSION,
        "seed": config.seed,
        "distance": config.distance,
        "rounds": config.rounds,
        "data_pauli_x_rate": config.data_pauli_x_rate,
        "syndrome_measurement_rate": config.syndrome_measurement_rate,
        "logical_bit": config.logical_bit,
        "logical_outcome": logical_outcome,
        "decoder_success": decoder_success,
        "logical_error": logical_error,
        "decoder_status": decoder.status,
        "syndrome_history": syndrome_history,
        "majority_syndrome": majority_syndrome,
        "provenance": adapt_result(
            "qec",
            {
                "logical_outcome": logical_outcome,
                "decoder_success": decoder_success,
                "logical_error": logical_error,
                "decoder_status": decoder.status,
            },
            run_id=f"qec-validation-{config.seed}-{config.distance}-{config.rounds}",
            backend_name="python",
            configuration={
                "validation_version": QEC_VALIDATION_VERSION,
                "seed": config.seed,
                "distance": config.distance,
                "rounds": config.rounds,
                "data_pauli_x_rate": config.data_pauli_x_rate,
                "syndrome_measurement_rate": config.syndrome_measurement_rate,
                "todo_id": 552,
                "tolerance_version": _TOLERANCE_VERSION,
                "replayable": True,
            },
        ),
    }
    return result


def run_validation_matrix(*, seed: int) -> list[dict[str, object]]:
    """Run the fixed 3x3x3x3 validation matrix in stable order."""
    results = []
    index = 0
    for distance in _ALLOWED_DISTANCES:
        for rounds in _ALLOWED_ROUNDS:
            for data_rate in _ALLOWED_RATES:
                for syndrome_rate in _ALLOWED_RATES:
                    results.append(
                        simulate_repeated_rounds(
                            QECValidationConfig(
                                seed=seed + index,
                                distance=distance,
                                rounds=rounds,
                                data_pauli_x_rate=data_rate,
                                syndrome_measurement_rate=syndrome_rate,
                            )
                        )
                    )
                    index += 1
    return results


def _result_digest(results: list[dict[str, object]]) -> str:
    summary = [
        {
            key: result[key]
            for key in (
                "seed",
                "distance",
                "rounds",
                "data_pauli_x_rate",
                "syndrome_measurement_rate",
                "logical_outcome",
                "decoder_success",
                "logical_error",
                "decoder_status",
            )
        }
        for result in results
    ]
    payload = json.dumps(summary, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_regression_baseline() -> dict[str, object]:
    """Load the checked-in matrix baseline used for drift detection."""
    path = Path(__file__).resolve().parents[2] / "research" / "qec_validation_baseline.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_regression_baseline(
    results: list[dict[str, object]], baseline: dict[str, object]
) -> dict[str, str]:
    """Reject tolerance, version, cardinality, or deterministic result drift."""
    if baseline.get("tolerance_version") != _TOLERANCE_VERSION:
        raise ValueError("tolerance version drift detected")
    if baseline.get("validation_version") != QEC_VALIDATION_VERSION:
        raise ValueError("validation version drift detected")
    if baseline.get("cases") != len(results):
        raise ValueError("regression case count drift detected")
    if baseline.get("result_digest") != _result_digest(results):
        raise ValueError("regression result drift detected")
    return {"status": "pass", "tolerance_version": _TOLERANCE_VERSION}


def replay_validation(config: QECValidationConfig) -> dict[str, object]:
    """Replay one validation run through the normalized benchmark contract."""
    return replay_local(
        "qec",
        seed=config.seed,
        execute=lambda seed: {
            "status": "pass",
            "validation": simulate_repeated_rounds(
                QECValidationConfig(
                    seed=seed,
                    distance=config.distance,
                    rounds=config.rounds,
                    data_pauli_x_rate=config.data_pauli_x_rate,
                    syndrome_measurement_rate=config.syndrome_measurement_rate,
                    logical_bit=config.logical_bit,
                )
            ),
        },
    )