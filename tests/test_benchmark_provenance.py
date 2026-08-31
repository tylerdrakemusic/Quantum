from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from quantum_toolkit.benchmark_provenance import (
    MANIFEST_VERSION,
    adapt_result,
    normalize_legacy_result,
    normalize_result,
    validate_manifest,
)


def _manifest() -> dict:
    return {
        "manifest_version": MANIFEST_VERSION,
        "identity": {
            "run_id": "run-123",
            "family": "shor",
            "algorithm": "shor",
        },
        "execution": {"started_at": "2026-08-31T12:00:00Z", "duration_seconds": 1.2},
        "backend": {"name": "aer_simulator", "provider": "qiskit_aer"},
        "configuration": {"n_value": 15, "shots": 1024},
        "result": {"success": True, "factor_found": 3},
        "timestamp": "2026-08-31T12:00:01Z",
        "evidence_references": ["proof/run-123.json"],
    }


def test_validate_manifest_accepts_versioned_complete_manifest() -> None:
    manifest = _manifest()

    assert validate_manifest(manifest) == manifest


def test_validate_manifest_rejects_missing_required_section() -> None:
    manifest = _manifest()
    del manifest["evidence_references"]

    with pytest.raises(ValueError, match="evidence_references"):
        validate_manifest(manifest)


def test_normalize_legacy_result_preserves_values_and_marks_unavailable_fields_null() -> None:
    legacy = {"backend": "old-aer", "success": False, "timestamp": "2024-01-01T00:00:00Z"}

    normalized = normalize_legacy_result(legacy, family="shor")

    assert normalized["provenance_status"] == "legacy"
    assert normalized["backend"]["name"] == "old-aer"
    assert normalized["identity"]["family"] == "shor"
    assert normalized["identity"]["run_id"] is None
    assert normalized["evidence_references"] is None
    assert legacy == {"backend": "old-aer", "success": False, "timestamp": "2024-01-01T00:00:00Z"}


@pytest.mark.parametrize("family", ["shor", "vqe", "qaoa", "qec", "quantum_kernel"])
def test_every_benchmark_family_adapts_to_the_same_manifest(family: str) -> None:
    manifest = adapt_result(
        family,
        {"success": True, "backend": "aer", "timestamp": "2026-08-31T12:00:00Z"},
        run_id=f"{family}-run-1",
    )

    assert manifest["manifest_version"] == MANIFEST_VERSION
    assert manifest["identity"]["family"] == family
    assert manifest["backend"]["name"] == "aer"
    assert normalize_result(manifest, family=family) == manifest