from __future__ import annotations

import math
import random
from typing import Sequence

from .evidence import EvidenceBundle
from .protocol import Diagnostic, Diagnostics, FloquetIsingProtocol, NoiseConfig, Provenance, ResponseTrace, ValidationStatus


CAPABILITY_VERSION = "1.0.0"
NOISY_CAPABILITY_VERSION = "3.0.0"
SHUFFLED_NULL_PERMUTATIONS = 64
LIFETIME_THRESHOLD = 0.5
LIFETIME_MINIMUM_WINDOW = 4


def run_floquet_ising(
    protocol: FloquetIsingProtocol,
    *,
    seed: int | None,
    initial_state: str = "all_zero",
) -> EvidenceBundle:
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or seed < 0):
        raise ValueError("seed must be a non-negative integer or None")
    if initial_state not in ("all_zero", "all_one", "alternating"):
        raise ValueError("initial_state must be all_zero, all_one, or alternating")
    rng = random.Random(seed)
    fields = tuple(rng.uniform(-protocol.disorder_strength, protocol.disorder_strength) for _ in range(protocol.system_size))
    state = _initial_state(protocol.system_size, initial_state)
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
    control_trace = _run_control_trace(protocol, fields, seed, initial_state)
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


def run_noisy_floquet_ising(
    protocol: FloquetIsingProtocol,
    *,
    seed: int,
    noise: NoiseConfig,
    initial_state: str = "all_zero",
) -> EvidenceBundle:
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if initial_state not in ("all_zero", "all_one", "alternating"):
        raise ValueError("initial_state must be all_zero, all_one, or alternating")
    rng = random.Random(seed)
    fields = tuple(rng.uniform(-protocol.disorder_strength, protocol.disorder_strength) for _ in range(protocol.system_size))
    trace = _measure_trace_with_noise(protocol, fields, rng, noise, initial_state)
    amplitude = _alternating_amplitude(trace.values)
    baseline = run_floquet_ising(protocol, seed=seed, initial_state=initial_state)
    baseline_amplitude = _alternating_amplitude(baseline.response_trace.values)
    response = Diagnostic("pass" if amplitude >= 0.5 else "fail", amplitude, "noisy alternating component")
    lifetime = _lifetime_diagnostic(trace.values)
    dominance_ratio = 0.0 if baseline_amplitude == 0.0 else amplitude / baseline_amplitude
    noise_dominance = Diagnostic(
        "fail" if dominance_ratio < 0.5 else "pass",
        dominance_ratio,
        "noisy-to-ideal alternating amplitude ratio",
        {"ideal_amplitude": baseline_amplitude, "noise_digest": noise.digest},
    )
    finite_size = Diagnostic(
        "inconclusive",
        None,
        "finite-size scaling control requires a multi-size comparison",
        {"system_size": protocol.system_size, "minimum_system_size": 3, "periods": protocol.periods},
    )
    failures: list[str] = []
    if response.status != "pass":
        failures.append("subharmonic_response_failed")
    if noise_dominance.status != "pass":
        failures.append("noise_dominated")
    if lifetime.status != "pass":
        failures.append("lifetime_criterion_failed")
    if finite_size.status != "pass":
        failures.append("finite_size_control_incomplete")
    status = ValidationStatus.CANDIDATE if not failures else ValidationStatus.INCONCLUSIVE
    return EvidenceBundle(
        status=status,
        provenance=Provenance(
            NOISY_CAPABILITY_VERSION,
            "v2",
            protocol.digest,
            "aer_noisy_simulation",
            seed,
            simulator="local_aer_style",
            noise_config_digest=noise.digest,
        ),
        response_trace=trace,
        diagnostics=Diagnostics(
            response,
            Diagnostic(
                "inconclusive",
                None,
                "noisy robustness controls are limited to coherent over-rotation, depolarizing, and readout noise",
            ),
            baseline_response=Diagnostic("pass", baseline_amplitude, "ideal baseline retained separately"),
            noise_dominance=noise_dominance,
            lifetime=lifetime,
            finite_size_false_positive=finite_size,
        ),
        failure_modes=tuple(failures),
        reproducibility={
            "seed_policy": "explicit_local_seed",
            "algorithm": "python_random_mt19937",
            "coherent_noise": "constant_pulse_angle_offset",
            "coherent_pulse_angle_offset_radians": noise.coherent_pulse_angle_offset,
            "evolution_noise": (
                "coherent_pulse_angle_offset_then_depolarizing_pauli_channel"
                if noise.coherent_pulse_angle_offset != 0.0
                else "depolarizing_pauli_channel"
            ),
            "measurement_noise": "readout_bit_flip",
            "measurement_policy": "seeded_projective_with_separate_evolution_and_readout_noise",
            "ideal_baseline": "separate_evidence_bundle",
        },
        noise=noise,
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
    protocol: FloquetIsingProtocol, fields: Sequence[float], seed: int | None, initial_state: str
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
    return _measure_trace(control_protocol, fields, random.Random(None if seed is None else seed + 2), initial_state)


def _initial_state(size: int, initial_state: str) -> list[complex]:
    state = [0j] * (1 << size)
    if initial_state == "all_zero":
        index = 0
    elif initial_state == "all_one":
        index = (1 << size) - 1
    else:
        index = sum(1 << bit for bit in range(size) if bit % 2 == 1)
    state[index] = 1.0 + 0j
    return state


def _measure_trace(
    protocol: FloquetIsingProtocol, fields: Sequence[float], rng: random.Random, initial_state: str
) -> ResponseTrace:
    state = _initial_state(protocol.system_size, initial_state)
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


def _measure_trace_with_noise(
    protocol: FloquetIsingProtocol,
    fields: Sequence[float],
    rng: random.Random,
    noise: NoiseConfig,
    initial_state: str,
) -> ResponseTrace:
    state = _initial_state(protocol.system_size, initial_state)
    values: list[float] = []
    uncertainties: list[float] = []
    for _ in range(protocol.periods):
        _apply_interactions(state, protocol, fields)
        for qubit in range(protocol.system_size):
            _apply_rx(
                state,
                protocol.system_size,
                qubit,
                protocol.pulse_angle + noise.coherent_pulse_angle_offset,
            )
        _apply_depolarizing_channel(state, protocol.system_size, noise.depolarizing_probability, rng)
        probabilities = _basis_probabilities(state)
        samples = []
        for _ in range(protocol.repetitions):
            index = _sample_basis_index(probabilities, rng)
            for bit in range(protocol.system_size):
                if rng.random() < noise.readout_flip_probability:
                    index ^= 1 << bit
            samples.append(_magnetization_for_index(index, protocol.system_size))
        mean = sum(samples) / len(samples)
        variance = sum((sample - mean) ** 2 for sample in samples) / len(samples)
        values.append(mean)
        uncertainties.append(math.sqrt(variance / len(samples)))
    return ResponseTrace(protocol.periods, tuple(values), tuple(uncertainties), protocol.repetitions)


def _apply_depolarizing_channel(
    state: list[complex], size: int, probability: float, rng: random.Random
) -> None:
    for qubit in range(size):
        if rng.random() >= probability:
            continue
        pauli = rng.randrange(3)
        mask = 1 << qubit
        if pauli == 0:
            for index in range(len(state)):
                if index & mask == 0:
                    other = index | mask
                    state[index], state[other] = state[other], state[index]
        elif pauli == 1:
            for index in range(len(state)):
                if index & mask == 0:
                    other = index | mask
                    zero, one = state[index], state[other]
                    state[index] = -1j * one
                    state[other] = 1j * zero
        else:
            for index in range(len(state)):
                if index & mask:
                    state[index] = -state[index]


def _basis_probabilities(state: Sequence[complex]) -> tuple[float, ...]:
    probabilities = tuple(abs(amplitude) ** 2 for amplitude in state)
    total = sum(probabilities)
    if not math.isclose(total, 1.0, rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError("ideal state probabilities are not normalized")
    return probabilities


def _sample_magnetization(
    probabilities: Sequence[float], size: int, rng: random.Random
) -> float:
    return _magnetization_for_index(_sample_basis_index(probabilities, rng), size)


def _sample_basis_index(probabilities: Sequence[float], rng: random.Random) -> int:
    target = rng.random()
    cumulative = 0.0
    for index, probability in enumerate(probabilities):
        cumulative += probability
        if target < cumulative or index == len(probabilities) - 1:
            return index
    raise RuntimeError("failed to sample ideal state probability")


def _magnetization_for_index(index: int, size: int) -> float:
    return sum(1 if index & (1 << bit) == 0 else -1 for bit in range(size)) / size