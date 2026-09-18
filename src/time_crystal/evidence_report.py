from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .comparative import ComparativeCase, ComparativeClassification, ComparativeMatrix, ComparativeRequest, Perturbation, run_comparative_matrix
from .evidence import EvidenceBundle
from .protocol import FloquetIsingProtocol, NoiseConfig


SCHEMA_VERSION = "v1"
MAX_REPORT_CASES = 256
MAX_REPORT_BYTES = 2_000_000


class ReplayValidationError(ValueError):
    """Raised when replayed comparative evidence differs from a report."""


@dataclass(frozen=True)
class ReplayResult:
    matched: bool
    request_digest: str
    case_count: int


@dataclass(frozen=True)
class EvidenceReport:
    request: ComparativeRequest
    cases: tuple[ComparativeCase, ...]
    declared_case_count: int
    max_cases: int
    provenance: dict[str, Any]
    schema_version: str = SCHEMA_VERSION
    case_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {self.schema_version}")
        if not 1 <= self.max_cases <= MAX_REPORT_CASES:
            raise ValueError("max_cases exceeds the report payload limit")
        if not self.cases or len(self.cases) > self.max_cases or self.declared_case_count < len(self.cases):
            raise ValueError("report cases must be non-empty and counts consistent")
        if self.case_digests and len(self.case_digests) != len(self.cases):
            raise ValueError("report case digests are inconsistent")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request": _request_to_dict(self.request),
            "declared_case_count": self.declared_case_count,
            "max_cases": self.max_cases,
            "provenance": self.provenance,
            "cases": [
                _case_to_dict(case, case_digest=digest)
                for case, digest in zip(self.cases, self.case_digests or tuple(case.digest for case in self.cases))
            ],
        }

    def to_json(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_REPORT_BYTES:
            raise ValueError("evidence report exceeds the payload size limit")
        return encoded

    @classmethod
    def from_json(cls, value: str) -> EvidenceReport:
        if not isinstance(value, str):
            raise ValueError("evidence report JSON must be a string")
        if len(value.encode("utf-8")) > MAX_REPORT_BYTES:
            raise ValueError("evidence report exceeds the payload size limit")
        try:
            payload = json.loads(value, parse_constant=_reject_json_constant)
        except (TypeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("malformed evidence report JSON") from exc
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvidenceReport:
        if not isinstance(payload, Mapping):
            raise ValueError("evidence report must be an object")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {payload.get('schema_version')}")
        required = {"schema_version", "request", "declared_case_count", "max_cases", "provenance", "cases"}
        missing = sorted(required - set(payload))
        if missing:
            raise ValueError(f"missing report field: {missing[0]}")
        cases = payload["cases"]
        if not isinstance(cases, list):
            raise ValueError("cases must be a list")
        if not isinstance(payload["provenance"], Mapping):
            raise ValueError("provenance must be an object")
        if not _is_int(payload["declared_case_count"]) or not _is_int(payload["max_cases"]):
            raise ValueError("case counts must be integers")
        request = _request_from_dict(payload["request"])
        parsed_cases = tuple(_case_from_dict(item) for item in cases)
        return cls(
            request=request,
            cases=parsed_cases,
            declared_case_count=payload["declared_case_count"],
            max_cases=payload["max_cases"],
            provenance=dict(payload["provenance"]),
            case_digests=tuple(item["case_digest"] for item in cases),
        )


def build_evidence_report(request: ComparativeRequest, matrix: ComparativeMatrix) -> EvidenceReport:
    """Wrap an in-memory comparative result in a bounded replayable report."""
    if not isinstance(request, ComparativeRequest) or not isinstance(matrix, ComparativeMatrix):
        raise TypeError("request and matrix must be time-crystal comparative types")
    if matrix.max_cases != request.max_cases:
        raise ValueError("matrix max_cases does not match request")
    if request.max_cases > MAX_REPORT_CASES:
        raise ValueError("request exceeds the report case limit")
    return EvidenceReport(
        request=request,
        cases=matrix.cases,
        declared_case_count=matrix.declared_case_count,
        max_cases=matrix.max_cases,
        provenance=dict(matrix.provenance),
        case_digests=tuple(case.digest for case in matrix.cases),
    )


def replay_evidence_report(report: EvidenceReport, request: ComparativeRequest) -> ReplayResult:
    """Replay a report and fail closed when inputs or evidence do not match."""
    if not isinstance(report, EvidenceReport) or not isinstance(request, ComparativeRequest):
        raise TypeError("report and request must be time-crystal evidence types")
    if _request_digest(report.request) != _request_digest(request):
        raise ReplayValidationError("request digest mismatch")
    replayed = build_evidence_report(request, run_comparative_matrix(request))
    if replayed.declared_case_count != report.declared_case_count or len(replayed.cases) != len(report.cases):
        raise ReplayValidationError("case count mismatch")
    declared_digests = report.case_digests or tuple(case.digest for case in report.cases)
    for expected, actual, declared_digest in zip(report.cases, replayed.cases, declared_digests):
        if expected.classification is not actual.classification:
            raise ReplayValidationError("classification mismatch")
        if declared_digest != actual.digest:
            raise ReplayValidationError("case digest mismatch")
        if expected.evidence.to_dict() != actual.evidence.to_dict():
            raise ReplayValidationError("evidence mismatch")
    return ReplayResult(True, _request_digest(request), len(replayed.cases))


def _request_to_dict(request: ComparativeRequest) -> dict[str, Any]:
    return {
        "protocol": request.protocol.as_dict(),
        "noise_models": [noise.as_dict() for noise in request.noise_models],
        "perturbations": [{"kind": item.kind, "value": item.value} for item in request.perturbations],
        "system_sizes": list(request.system_sizes),
        "seed": request.seed,
        "max_cases": request.max_cases,
        "stable_pulse_boundaries": request.stable_pulse_boundaries,
    }


def _request_from_dict(payload: Any) -> ComparativeRequest:
    if not isinstance(payload, Mapping):
        raise ValueError("request must be an object")
    required = {"protocol", "noise_models", "perturbations", "system_sizes", "seed", "max_cases", "stable_pulse_boundaries"}
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"missing request field: {missing[0]}")
    if not isinstance(payload["noise_models"], list) or not isinstance(payload["perturbations"], list) or not isinstance(payload["system_sizes"], list):
        raise ValueError("request collections must be lists")
    try:
        return ComparativeRequest(
            protocol=FloquetIsingProtocol(**_object(payload["protocol"], "protocol")),
            noise_models=tuple(NoiseConfig(**_object(item, "noise model")) for item in payload["noise_models"]),
            perturbations=tuple(Perturbation(**_object(item, "perturbation")) for item in payload["perturbations"]),
            system_sizes=tuple(payload["system_sizes"]),
            seed=payload["seed"],
            max_cases=payload["max_cases"],
            stable_pulse_boundaries=payload["stable_pulse_boundaries"],
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("malformed request") from exc


def _case_to_dict(case: ComparativeCase, *, case_digest: str | None = None) -> dict[str, Any]:
    unavailable = None if case.evidence.evidence is None else {
        "reason": case.evidence.evidence.reason,
        "source": case.evidence.evidence.source,
    }
    return {
        "case_digest": case.digest if case_digest is None else case_digest,
        "protocol": None if case.protocol is None else case.protocol.as_dict(),
        "protocol_digest": None if case.protocol is None else case.protocol.digest,
        "noise": case.noise.as_dict(),
        "noise_digest": case.noise.digest,
        "perturbation": {"kind": case.perturbation.kind, "value": case.perturbation.value},
        "classification": case.classification.value,
        "diagnostics": case.diagnostics,
        "unavailable": unavailable,
        "evidence": case.evidence.to_dict(),
    }


def _case_from_dict(payload: Any) -> ComparativeCase:
    if not isinstance(payload, Mapping):
        raise ValueError("case must be an object")
    required = {"case_digest", "protocol", "protocol_digest", "noise", "noise_digest", "perturbation", "classification", "diagnostics", "unavailable", "evidence"}
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"missing case field: {missing[0]}")
    protocol_data = payload["protocol"]
    protocol = None if protocol_data is None else FloquetIsingProtocol(**_object(protocol_data, "case protocol"))
    noise = NoiseConfig(**_object(payload["noise"], "case noise"))
    evidence_payload = payload["evidence"]
    if not isinstance(evidence_payload, Mapping):
        raise ValueError("case evidence must be an object")
    try:
        evidence = EvidenceBundle.from_json(json.dumps(dict(evidence_payload), allow_nan=False))
        classification = ComparativeClassification(payload["classification"])
        perturbation = Perturbation(**_object(payload["perturbation"], "case perturbation"))
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("malformed case") from exc
    if not isinstance(payload["diagnostics"], Mapping) or not isinstance(payload["case_digest"], str):
        raise ValueError("malformed case metadata")
    expected_protocol_digest = None if protocol is None else protocol.digest
    if payload["protocol_digest"] != expected_protocol_digest or payload["noise_digest"] != noise.digest:
        raise ValueError("case identity digest does not match its inputs")
    unavailable = payload["unavailable"]
    expected_unavailable = None if evidence.evidence is None else {
        "reason": evidence.evidence.reason,
        "source": evidence.evidence.source,
    }
    if unavailable != expected_unavailable:
        raise ValueError("case unavailable details do not match evidence")
    return ComparativeCase(protocol, noise, perturbation, classification, evidence, dict(payload["diagnostics"]))


def _request_digest(request: ComparativeRequest) -> str:
    from hashlib import sha256

    encoded = json.dumps(_request_to_dict(request), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"invalid JSON constant: {value}")