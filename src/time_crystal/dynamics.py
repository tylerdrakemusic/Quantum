from __future__ import annotations

import math
import random
from typing import Sequence

from .evidence import EvidenceBundle
from .protocol import Diagnostic, Diagnostics, FloquetIsingProtocol, Provenance, ResponseTrace, ValidationStatus


CAPABILITY_VERSION = "1.0.0"


def run_floquet_ising(protocol: FloquetIsingProtocol, *, seed: int | None) -> EvidenceBundle:
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or seed < 0):
        raise ValueError("seed must be a non-negative integer or None")
    rng = random.Random(seed)
    fields = tuple(rng.uniform(-protocol.disorder_strength, protocol.disorder_strength) for _ in range(protocol.system_size))
    state = [0j] * (1 << protocol.system_size)
    state[0] = 1.0 + 0j
    values: list[float] = []
    for _ in range(protocol.periods):
        _apply_interactions(state, protocol, fields)
        for qubit in range(protocol.system_size):
            _apply_rx(state, protocol.system_size, qubit, protocol.pulse_angle)
        values.append(_measure_magnetization(state, protocol.system_size))
    trace = ResponseTrace(protocol.periods, tuple(values))
    alternating = abs(sum(((-1) ** index) * value for index, value in enumerate(values)) / len(values))
    response_status = "pass" if alternating >= 0.5 else "fail"
    limitations_status = "insufficient_controls" if protocol.periods < 8 else "insufficient_controls"
    failures: list[str] = []
    if response_status == "fail":
        failures.append("subharmonic_response_failed")
    if protocol.periods < 8:
        failures.append("insufficient_time_window")
    status = ValidationStatus.CANDIDATE if response_status == "pass" and not failures else ValidationStatus.INCONCLUSIVE
    return EvidenceBundle(
        status=status,
        provenance=Provenance(CAPABILITY_VERSION, "v1", protocol.digest, "local_ideal_simulation", seed),
        response_trace=trace,
        diagnostics=Diagnostics(
            Diagnostic(response_status, alternating, "alternating component"),
            Diagnostic(limitations_status, None, "robustness and scaling controls are not part of this slice"),
        ),
        failure_modes=tuple(failures),
        reproducibility={"seed_policy": "explicit_local_seed", "algorithm": "python_random_mt19937"},
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