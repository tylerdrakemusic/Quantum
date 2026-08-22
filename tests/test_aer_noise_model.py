from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from utils.aer_noise_model import build_noise_model


def calibration_snapshot() -> dict[str, object]:
    fixture_path = Path(__file__).parent / "fixtures" / "ibm_fez_2026-08-22.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def test_build_maps_supported_calibration_and_exposes_provenance() -> None:
    result = build_noise_model(
        calibration_snapshot(),
        model_version="fez-aer-v1",
        seed=17,
        observed_at=datetime(2026, 8, 22, 8, 10, tzinfo=timezone.utc),
    )

    assert result.status == "ready"
    assert result.noise_model is not None
    assert result.metadata == {
        "calibration_timestamp": "2026-08-22T08:00:00Z",
        "source_identifiers": {
            "backend_name": "ibm_fez",
            "provider": "ibm_quantum",
            "source": "backend-properties-api:v1",
        },
        "model_version": "fez-aer-v1",
        "seed": 17,
        "supported_mappings": ["gate_error", "readout_error", "T1", "T2"],
        "proxy_mappings": ["gate_error->depolarizing_error", "readout_error->readout_error"],
        "unsupported_fields": ["cross_talk", "drift", "pulse_schedule"],
        "warnings": ["Aer with an IBM-derived approximate noise model"],
    }


def test_same_snapshot_and_seed_build_identical_noise_models() -> None:
    kwargs = {
        "model_version": "fez-aer-v1",
        "seed": 17,
        "observed_at": datetime(2026, 8, 22, 8, 10, tzinfo=timezone.utc),
    }

    first = build_noise_model(calibration_snapshot(), **kwargs)
    second = build_noise_model(calibration_snapshot(), **kwargs)

    assert first.noise_model.to_dict() == second.noise_model.to_dict()
    assert first.metadata == second.metadata


def test_missing_snapshot_is_explicitly_non_authoritative() -> None:
    result = build_noise_model(None, model_version="fez-aer-v1", seed=1)

    assert result.status == "missing"
    assert result.noise_model is None
    assert "calibration snapshot is missing" in result.metadata["warnings"]


def test_stale_snapshot_is_explicitly_non_authoritative() -> None:
    snapshot = calibration_snapshot()
    snapshot["last_update_date"] = "2026-08-01T08:00:00Z"

    result = build_noise_model(
        snapshot,
        model_version="fez-aer-v1",
        seed=1,
        observed_at=datetime(2026, 8, 22, 8, 10, tzinfo=timezone.utc),
    )

    assert result.status == "stale"
    assert result.noise_model is None
    assert "calibration snapshot is stale" in result.metadata["warnings"]


def test_aging_snapshot_is_explicitly_non_authoritative() -> None:
    snapshot = calibration_snapshot()
    snapshot["last_update_date"] = "2026-08-21T08:00:00Z"

    result = build_noise_model(
        snapshot,
        model_version="fez-aer-v1",
        seed=1,
        observed_at=datetime(2026, 8, 22, 8, 10, tzinfo=timezone.utc),
    )

    assert result.status == "aging"
    assert result.noise_model is None
    assert any("calibration snapshot is aging" in warning for warning in result.metadata["warnings"])


def test_future_snapshot_is_explicitly_non_authoritative() -> None:
    snapshot = calibration_snapshot()
    snapshot["last_update_date"] = "2026-08-22T08:11:00Z"

    result = build_noise_model(
        snapshot,
        model_version="fez-aer-v1",
        seed=1,
        observed_at=datetime(2026, 8, 22, 8, 10, tzinfo=timezone.utc),
    )

    assert result.status == "future"
    assert result.noise_model is None
    assert "calibration timestamp is in the future" in result.metadata["warnings"]


def test_wrong_backend_is_explicitly_non_authoritative() -> None:
    snapshot = calibration_snapshot()
    snapshot["backend_name"] = "other_backend"

    result = build_noise_model(snapshot, model_version="fez-aer-v1", seed=1)

    assert result.status == "wrong_backend"
    assert result.noise_model is None
    assert any("unexpected backend_name" in warning for warning in result.metadata["warnings"])


def test_wrong_source_is_explicitly_non_authoritative() -> None:
    snapshot = calibration_snapshot()
    snapshot["source"] = "other-source:v1"

    result = build_noise_model(snapshot, model_version="fez-aer-v1", seed=1)

    assert result.status == "wrong_source"
    assert result.noise_model is None
    assert any("unexpected calibration snapshot source" in warning for warning in result.metadata["warnings"])


def test_invalid_calibration_ranges_are_reported_without_authoritative_model() -> None:
    snapshot = calibration_snapshot()
    snapshot["qubits"]["0"]["readout_error"] = 1.1
    snapshot["gates"]["x"]["0"]["gate_error"] = -0.1

    result = build_noise_model(snapshot, model_version="fez-aer-v1", seed=1)

    assert result.status == "unmappable"
    assert result.noise_model is None
    assert "invalid calibration ranges" in result.metadata["warnings"]


def test_unmappable_fields_are_reported_without_authoritative_model() -> None:
    snapshot = calibration_snapshot()
    snapshot["qubits"] = {"0": {"unknown_error": 0.4}}

    result = build_noise_model(snapshot, model_version="fez-aer-v1", seed=1)

    assert result.status == "unmappable"
    assert result.noise_model is None
    assert "unknown_error" in result.metadata["unsupported_fields"]
    assert "unmappable calibration data" in result.metadata["warnings"]


def test_undated_snapshot_is_explicitly_non_authoritative() -> None:
    snapshot = calibration_snapshot()
    snapshot.pop("last_update_date")

    result = build_noise_model(snapshot, model_version="fez-aer-v1", seed=1)

    assert result.status == "undated"
    assert result.noise_model is None
    assert "calibration timestamp is missing or invalid" in result.metadata["warnings"]