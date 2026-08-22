"""Deterministic Aer noise models from versioned IBM calibration snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Literal

from qiskit_aer.noise import (
    NoiseModel,
    ReadoutError,
    depolarizing_error,
    thermal_relaxation_error,
)

BuildStatus = Literal["ready", "missing", "undated", "aging", "stale", "unmappable"]

_UNSUPPORTED_FIELDS = ["cross_talk", "drift", "pulse_schedule"]
_APPROXIMATION_WARNING = "Aer with an IBM-derived approximate noise model"


@dataclass(frozen=True)
class NoiseModelBuildResult:
    """A noise model and the provenance decision made while building it."""

    status: BuildStatus
    noise_model: NoiseModel | None
    metadata: dict[str, Any]


def build_noise_model(
    snapshot: dict[str, Any] | None,
    *,
    model_version: str,
    seed: int,
    observed_at: datetime | None = None,
) -> NoiseModelBuildResult:
    """Build a deterministic approximate Aer model from one calibration snapshot."""
    metadata = _base_metadata(snapshot, model_version, seed)
    if snapshot is None:
        metadata["warnings"] = ["calibration snapshot is missing"]
        return NoiseModelBuildResult("missing", None, metadata)

    calibration_timestamp = snapshot.get("last_update_date")
    update_time = _parse_timestamp(calibration_timestamp)
    if update_time is None:
        metadata["warnings"] = ["calibration timestamp is missing or invalid"]
        return NoiseModelBuildResult("undated", None, metadata)

    now = observed_at or datetime.now(timezone.utc)
    age = now - update_time
    if age > timedelta(days=7):
        metadata["warnings"] = ["calibration snapshot is stale"]
        return NoiseModelBuildResult("stale", None, metadata)
    if age > timedelta(days=1):
        metadata["warnings"] = ["calibration snapshot is aging and not current-state authoritative"]
        return NoiseModelBuildResult("aging", None, metadata)

    unsupported = _find_unsupported_fields(snapshot)
    metadata["unsupported_fields"] = unsupported + _UNSUPPORTED_FIELDS
    if unsupported:
        metadata["warnings"] = ["unmappable calibration data"]
        return NoiseModelBuildResult("unmappable", None, metadata)

    model = NoiseModel()
    qubits = snapshot.get("qubits", {})
    gates = snapshot.get("gates", {})
    if not qubits or not gates:
        metadata["warnings"] = ["unmappable calibration data"]
        return NoiseModelBuildResult("unmappable", None, metadata)

    for qubit, values in sorted(qubits.items(), key=lambda item: int(item[0])):
        readout_probability = values.get("readout_error")
        if readout_probability is not None:
            model.add_readout_error(
                _with_deterministic_id(
                    ReadoutError(
                    [
                        [1 - readout_probability, readout_probability],
                        [readout_probability, 1 - readout_probability],
                    ]
                    ),
                    "readout",
                    qubit,
                    readout_probability,
                ),
                [int(qubit)],
            )

    for gate_name, gate_entries in sorted(gates.items()):
        for qubit_key, values in sorted(gate_entries.items()):
            qubits_for_gate = [int(value) for value in qubit_key.split("-")]
            error_probability = values.get("gate_error")
            if error_probability is None:
                continue
            error = depolarizing_error(error_probability, len(qubits_for_gate))
            if len(qubits_for_gate) == 1:
                calibration = qubits[str(qubits_for_gate[0])]
                if "T1" in calibration and "T2" in calibration and "gate_length" in values:
                    error = thermal_relaxation_error(
                        calibration["T1"], calibration["T2"], values["gate_length"]
                    ).compose(error)
            error = _with_deterministic_id(error, gate_name, qubit_key, values)
            model.add_quantum_error(error, gate_name, qubits_for_gate)

    return NoiseModelBuildResult("ready", model, metadata)


def _base_metadata(snapshot: dict[str, Any] | None, model_version: str, seed: int) -> dict[str, Any]:
    source = snapshot or {}
    return {
        "calibration_timestamp": source.get("last_update_date"),
        "source_identifiers": {
            "backend_name": source.get("backend_name"),
            "provider": source.get("provider"),
            "source": source.get("source"),
        },
        "model_version": model_version,
        "seed": seed,
        "supported_mappings": ["gate_error", "readout_error", "T1", "T2"],
        "proxy_mappings": ["gate_error->depolarizing_error", "readout_error->readout_error"],
        "unsupported_fields": list(_UNSUPPORTED_FIELDS),
        "warnings": [_APPROXIMATION_WARNING],
    }


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _find_unsupported_fields(snapshot: dict[str, Any]) -> list[str]:
    known_qubit_fields = {"T1", "T2", "readout_error"}
    known_gate_fields = {"gate_error", "gate_length"}
    found: set[str] = set()
    for values in snapshot.get("qubits", {}).values():
        found.update(set(values) - known_qubit_fields)
    for gate_entries in snapshot.get("gates", {}).values():
        for values in gate_entries.values():
            found.update(set(values) - known_gate_fields)
    return sorted(found)


def _with_deterministic_id(error: Any, kind: str, qubits: str, values: object) -> Any:
    payload = json.dumps([kind, qubits, values], sort_keys=True, separators=(",", ":"))
    error._id = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return error