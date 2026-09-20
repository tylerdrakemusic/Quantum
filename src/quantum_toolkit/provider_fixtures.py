"""Static provider availability snapshots for planner tests and dry runs."""

from __future__ import annotations

from quantum_toolkit.execution_planner import AvailabilitySnapshot


_FIXTURES = {
    "ibm": {
        "provider_id": "ibm-fez",
        "provider": "ibm",
        "execution_mode": "hardware",
        "available": True,
        "observed_at": "2026-09-19T11:59:00Z",
        "freshness_seconds": 3600,
        "max_qubits": 156,
        "quota_remaining_seconds": 60,
    },
    "braket": {
        "provider_id": "braket-local",
        "provider": "braket",
        "execution_mode": "simulator",
        "available": True,
        "observed_at": "2026-09-19T11:58:00Z",
        "freshness_seconds": 3600,
        "max_qubits": 32,
        "quota_remaining_seconds": 0,
    },
    "local": {
        "provider_id": "local-aer",
        "provider": "local",
        "execution_mode": "simulator",
        "available": True,
        "observed_at": "2026-09-19T11:59:00Z",
        "freshness_seconds": 3600,
        "max_qubits": 32,
        "quota_remaining_seconds": 0,
    },
}


def fixture_snapshots(provider: str | None = None) -> tuple[AvailabilitySnapshot, ...]:
    """Return immutable static snapshots for one provider or the full fixture set."""
    selected = (provider,) if provider is not None else tuple(_FIXTURES)
    unknown = set(selected) - set(_FIXTURES)
    if unknown:
        raise ValueError(f"unknown provider fixture: {sorted(unknown)}")
    return tuple(AvailabilitySnapshot.from_dict(_FIXTURES[name]) for name in selected)