from __future__ import annotations

import math
import random
from typing import Sequence

from .evidence import EvidenceBundle
from .protocol import Diagnostic, Diagnostics, FloquetIsingProtocol, Provenance, ResponseTrace, ValidationStatus


CAPABILITY_VERSION = "1.0.0"
SHUFFLED_NULL_PERMUTATIONS = 64
LIFETIME_THRESHOLD = 0.5
LIFETIME_MINIMUM_WINDOW = 4


def run_floquet_ising(protocol: FloquetIsingProtocol, *, seed: int | None) -> EvidenceBundle:
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or seed < 0):
        raise ValueError("seed must be a non-negative integer or None")
    rng = random.Random(seed)
    fields = tuple(rng.uniform(-protocol.disorder_strength, protocol.disorder_strength) for _ in range(protocol.system_size))
    state = [0j] * (1 << protocol.system_size)
    state[0] = 1.0 + 0j
    values: list[float] = []
    uncertainties: list[float] = []
    for _ in range(protocol.periods):
        _apply_interactions(state, protocol, fields)
        for qubit in range(protocol.system_size):
            _apply_rx(state, protocol.system_size, qubit, protocol.pulse_angle)
        probabilities = _basis_probabilities(state)
        samples = [
            _sample_magnetization(probabilities, protocol.system_size, rng)
            for _ in range(protocol.repetitions)
        ]
        mean = sum(samples) / len(samples)
        variance = sum((sample - mean) ** 2 for sample in samples) / len(samples)
        values.append(mean)
        uncertainties.append(math.sqrt(variance / len(samples)))
    trace = ResponseTrace(protocol.periods, tuple(values), tuple(uncertainties), protocol.repetitions)
    alternating = _alternating_amplitude(values)
    response_status = "pass" if alternating >= 0.5 else "fail"
    spectral = Diagnostic(
        "pass" if alternating >= 0.5 else "fail",
        alternating,
        "half-frequency alternating estimator",
        {"estimator": "absolute_alternating_mean", "target_frequency": 0.5},
    )
    null = _shuffled_null_diagnostic(values, seed)
    lifetime = _lifetime_diagnostic(values)
    control_trace = _run_control_trace(protocol, fields, seed)
    control = Diagnostic(
        "pass" if _alternating_amplitude(control_trace.values) < 0.5 else "fail",
        _alternating_amplitude(control_trace.values),
        "zero-drive non-period-doubled control",
        {"control": "pulse_angle_zero", "periods": protocol.periods},
    )
    limitations_status = "insufficient_controls"
    failures: list[str] = []
    if response_status == "fail":
        failures.append("subharmonic_response_failed")
    if spectral.status != "pass":
        failures.append("half_frequency_diagnostic_failed")
    if null.status != "pass":
        failures.append("shuffled_null_failed")
    if lifetime.status != "pass":
        failures.append("lifetime_criterion_failed")
    if control.status != "pass":
        failures.append("non_period_doubled_control_failed")
    if protocol.periods < 8:
        failures.append("insufficient_time_window")
    status = ValidationStatus.CANDIDATE if not failures else ValidationStatus.INCONCLUSIVE
    return EvidenceBundle(
        status=status,
        provenance=Provenance(CAPABILITY_VERSION, "v1", protocol.digest, "local_ideal_simulation", seed),
        response_trace=trace,
        diagnostics=Diagnostics(
            Diagnostic(response_status, alternating, "alternating component"),
            Diagnostic(limitations_status, None, "robustness and scaling controls are not part of this slice"),
            spectral,
            null,
            lifetime,
            control,
        ),
        failure_modes=tuple(failures),
        reproducibility={
            "seed_policy": "explicit_local_seed",
            "algorithm": "python_random_mt19937",
            "measurement_policy": "seeded_projective_from_ideal_probabilities",
        },
        control_trace=control_trace,
    )


def _apply_interactions(state: list[complex], protocol: FloquetIsingProtocol, fields: Sequence[float]) -> None:
    size = protocol.system_size
    for index, amplitude in enumerate(state):
        spin_sum = sum(1 if index & (1 << bit) == 0 else -1 for bit in range(size))
        pair_sum = sum(
            (1 if index & (1 << bit) == 0 else -1) * (1 if index & (1 << (bit + 1)) == 0 else -1)
            for bit in range(size - 1)
        )
        phase = protocol.interaction_strength * pair_sum + sum(
            fields[bit] * (1 if index & (1 << bit) == 0 else -1) for bit in range(size)
        )
        state[index] = amplitude * complex(math.cos(phase), -math.sin(phase))


def _apply_rx(state: list[complex], size: int, qubit: int, angle: float) -> None:
    cosine = math.cos(angle / 2)
    sine = -1j * math.sin(angle / 2)
    mask = 1 << qubit
    for index in range(len(state)):
        if index & mask:
            continue
        other = index | mask
        zero, one = state[index], state[other]
        state[index] = cosine * zero + sine * one
        state[other] = sine * zero + cosine * one


def _measure_magnetization(state: Sequence[complex], size: int) -> float:
    total = 0.0
    for index, amplitude in enumerate(state):
        probability = abs(amplitude) ** 2
        total += probability * sum(1 if index & (1 << bit) == 0 else -1 for bit in range(size)) / size
    return total


def _alternating_amplitude(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return abs(sum(((-1) ** index) * value for index, value in enumerate(values)) / len(values))


def _shuffled_null_diagnostic(values: Sequence[float], seed: int | None) -> Diagnostic:
    rng = random.Random(None if seed is None else seed + 1)
    observed = _alternating_amplitude(values)
    exceedances = 0
    for _ in range(SHUFFLED_NULL_PERMUTATIONS):
        shuffled = list(values)
        rng.shuffle(shuffled)
        if _alternating_amplitude(shuffled) >= observed:
            exceedances += 1
    p_value = (exceedances + 1) / (SHUFFLED_NULL_PERMUTATIONS + 1)
    return Diagnostic(
        "pass" if p_value < 0.05 else "fail",
        p_value,
        "fixed-count shuffled-trace null comparison",
        {
            "estimator": "absolute_alternating_mean",
            "permutations": SHUFFLED_NULL_PERMUTATIONS,
            "seed_policy": "derived_from_run_seed",
            "p_value": p_value,
        },
    )


def _lifetime_diagnostic(values: Sequence[float]) -> Diagnostic:
    if not values or values[0] == 0.0:
        return Diagnostic(
            "fail",
            0.0,
            "relative-amplitude lifetime unavailable",
            {"threshold": LIFETIME_THRESHOLD, "minimum_window": LIFETIME_MINIMUM_WINDOW, "definition": "contiguous_relative_amplitude"},
        )
    baseline = abs(values[0])
    lifetime = 0
    for value in values:
        if abs(value) / baseline < LIFETIME_THRESHOLD:
            break
        lifetime += 1
    return Diagnostic(
        "pass" if lifetime >= LIFETIME_MINIMUM_WINDOW else "fail",
        float(lifetime),
        "contiguous relative-amplitude lifetime",
        {"threshold": LIFETIME_THRESHOLD, "minimum_window": LIFETIME_MINIMUM_WINDOW, "definition": "contiguous_relative_amplitude"},
    )


def _run_control_trace(
    protocol: FloquetIsingProtocol, fields: Sequence[float], seed: int | None
) -> ResponseTrace:
    control_protocol = FloquetIsingProtocol(
        system_size=protocol.system_size,
        periods=protocol.periods,
        repetitions=protocol.repetitions,
        pulse_angle=0.0,
        interaction_strength=protocol.interaction_strength,
        disorder_strength=protocol.disorder_strength,
        observable=protocol.observable,
    )
    return _measure_trace(control_protocol, fields, random.Random(None if seed is None else seed + 2))


def _measure_trace(
    protocol: FloquetIsingProtocol, fields: Sequence[float], rng: random.Random
) -> ResponseTrace:
    state = [0j] * (1 << protocol.system_size)
    state[0] = 1.0 + 0j
    values: list[float] = []
    uncertainties: list[float] = []
    for _ in range(protocol.periods):
        _apply_interactions(state, protocol, fields)
        for qubit in range(protocol.system_size):
            _apply_rx(state, protocol.system_size, qubit, protocol.pulse_angle)
        probabilities = _basis_probabilities(state)
        samples = [_sample_magnetization(probabilities, protocol.system_size, rng) for _ in range(protocol.repetitions)]
        mean = sum(samples) / len(samples)
        variance = sum((sample - mean) ** 2 for sample in samples) / len(samples)
        values.append(mean)
        uncertainties.append(math.sqrt(variance / len(samples)))
    return ResponseTrace(protocol.periods, tuple(values), tuple(uncertainties), protocol.repetitions)


def _basis_probabilities(state: Sequence[complex]) -> tuple[float, ...]:
    probabilities = tuple(abs(amplitude) ** 2 for amplitude in state)
    total = sum(probabilities)
    if not math.isclose(total, 1.0, rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError("ideal state probabilities are not normalized")
    return probabilities


def _sample_magnetization(
    probabilities: Sequence[float], size: int, rng: random.Random
) -> float:
    target = rng.random()
    cumulative = 0.0
    for index, probability in enumerate(probabilities):
        cumulative += probability
        if target < cumulative or index == len(probabilities) - 1:
            return sum(1 if index & (1 << bit) == 0 else -1 for bit in range(size)) / size
    raise RuntimeError("failed to sample ideal state probability")