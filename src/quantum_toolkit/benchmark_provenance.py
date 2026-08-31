"""Versioned provenance contract for Quantum benchmark runs.

The contract is additive: new writers emit a complete manifest, while readers
normalize historical rows without rewriting their source data.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from typing import Any, Mapping

MANIFEST_VERSION = "1.0"
MANIFEST_SCHEMA_VERSION = MANIFEST_VERSION
PROVENANCE_STATUS = "provenance"
LEGACY_STATUS = "legacy"
SUPPORTED_FAMILIES = frozenset({"shor", "vqe", "qaoa", "qec", "quantum_kernel"})
_SECTIONS = ("identity", "execution", "backend", "configuration", "result")


def validate_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a copy of a versioned benchmark manifest."""
    if not isinstance(manifest, Mapping):
        raise ValueError("manifest must be a mapping")
    required = {"manifest_version", *_SECTIONS, "timestamp", "evidence_references"}
    missing = sorted(required - set(manifest))
    if missing:
        raise ValueError(f"missing required manifest field: {missing[0]}")
    if manifest["manifest_version"] != MANIFEST_VERSION:
        raise ValueError("unsupported manifest_version")
    for section in _SECTIONS:
        if not isinstance(manifest[section], Mapping):
            raise ValueError(f"manifest section must be a mapping: {section}")
    references = manifest["evidence_references"]
    if not isinstance(references, list) or any(not isinstance(item, str) for item in references):
        raise ValueError("evidence_references must be a list of strings")
    if not isinstance(manifest["timestamp"], str):
        raise ValueError("timestamp must be a string")
    return deepcopy(dict(manifest))


def build_manifest(
    *,
    family: str,
    result: Mapping[str, Any],
    run_id: str | None = None,
    backend: Mapping[str, Any] | None = None,
    configuration: Mapping[str, Any] | None = None,
    execution: Mapping[str, Any] | None = None,
    timestamp: str | None = None,
    evidence_references: list[str] | None = None,
) -> dict[str, Any]:
    """Build a manifest while retaining unknown or unavailable values as null."""
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "provenance_status": PROVENANCE_STATUS,
        "identity": {"run_id": run_id, "family": family, "algorithm": family},
        "execution": dict(execution or {}),
        "backend": dict(backend or {}),
        "configuration": dict(configuration or {}),
        "result": dict(result),
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "evidence_references": list(evidence_references or []),
    }
    return validate_manifest(manifest)


def normalize_legacy_result(legacy: Mapping[str, Any], *, family: str) -> dict[str, Any]:
    """Return a comparable legacy view without changing the input mapping."""
    source = deepcopy(dict(legacy))
    backend_value = source.get("backend")
    normalized = {
        **source,
        "manifest_version": None,
        "provenance_status": LEGACY_STATUS,
        "identity": {"run_id": None, "family": family, "algorithm": family},
        "execution": {"started_at": None, "duration_seconds": None},
        "backend": {"name": backend_value, "provider": None},
        "configuration": None,
        "result": None,
        "timestamp": source.get("timestamp"),
        "evidence_references": None,
    }
    return normalized


def normalize_result(result: Mapping[str, Any], *, family: str) -> dict[str, Any]:
    """Normalize either a current manifest or a historical result row."""
    if result.get("manifest_version") == MANIFEST_VERSION:
        return validate_manifest(result)
    return normalize_legacy_result(result, family=family)


def adapt_result(
    family: str,
    result: Mapping[str, Any],
    *,
    run_id: str | None = None,
    backend_name: str | None = None,
    configuration: Mapping[str, Any] | None = None,
    evidence_references: list[str] | None = None,
) -> dict[str, Any]:
    """Adapt any benchmark-family result to the common writer contract."""
    if family not in SUPPORTED_FAMILIES:
        raise ValueError(f"unsupported benchmark family: {family}")
    return build_manifest(
        family=family,
        result=result,
        run_id=run_id,
        backend={"name": backend_name or result.get("backend"), "provider": None},
        configuration=configuration,
        evidence_references=evidence_references,
        timestamp=result.get("timestamp"),
    )


def persist_manifest(conn: Any, manifest: Mapping[str, Any]) -> int:
    """Persist one new manifest in the additive provenance table."""
    validated = validate_manifest(manifest)
    identity = validated["identity"]
    family = identity.get("family")
    run_id = identity.get("run_id")
    if family not in SUPPORTED_FAMILIES:
        raise ValueError("manifest identity.family must be a supported family")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("manifest identity.run_id is required for persistence")
    cursor = conn.execute(
        """INSERT INTO benchmark_provenance
           (run_id, identity_family, manifest_version, provenance_status,
            manifest_json, evidence_references_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id,
            family,
            validated["manifest_version"],
            validated["provenance_status"],
            json.dumps(validated, ensure_ascii=False, sort_keys=True),
            json.dumps(validated["evidence_references"], ensure_ascii=False),
            validated["timestamp"],
        ),
    )
    conn.commit()
    return int(getattr(cursor, "lastrowid", 0) or 0)


create_manifest = build_manifest
normalize_benchmark_result = normalize_result