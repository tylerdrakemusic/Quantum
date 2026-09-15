from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .protocol import (
    Diagnostic,
    Diagnostics,
    EvidenceUnavailable,
    Provenance,
    ResponseTrace,
    ValidationStatus,
)


class UnsupportedSchemaVersion(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceBundle:
    status: ValidationStatus
    provenance: Provenance
    response_trace: ResponseTrace | None
    diagnostics: Diagnostics | None
    failure_modes: tuple[str, ...]
    reproducibility: dict[str, Any]
    evidence: EvidenceUnavailable | None = None

    @classmethod
    def unavailable(cls, *, reason: str, source: str) -> EvidenceBundle:
        return cls(
            status=ValidationStatus.UNAVAILABLE,
            provenance=Provenance("1.0.0", "v1", "", source, None),
            response_trace=None,
            diagnostics=None,
            failure_modes=("evidence_unavailable",),
            reproducibility={"seed_policy": "unavailable"},
            evidence=EvidenceUnavailable(reason, source),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": "v1",
            "status": self.status.value,
            "provenance": {
                "capability_version": self.provenance.capability_version,
                "evidence_schema_version": self.provenance.evidence_schema_version,
                "protocol_digest": self.provenance.protocol_digest,
                "source": self.provenance.source,
                "seed": self.provenance.seed,
            },
            "response_trace": None
            if self.response_trace is None
            else {"periods": self.response_trace.periods, "values": list(self.response_trace.values)},
            "diagnostics": None
            if self.diagnostics is None
            else {
                "subharmonic_response": self._diagnostic_dict(self.diagnostics.subharmonic_response),
                "evidence_limitations": self._diagnostic_dict(self.diagnostics.evidence_limitations),
            },
            "failure_modes": list(self.failure_modes),
            "reproducibility": self.reproducibility,
            "evidence": None
            if self.evidence is None
            else {"reason": self.evidence.reason, "source": self.evidence.source},
        }
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> EvidenceBundle:
        payload = json.loads(value)
        if payload.get("schema_version") != "v1":
            raise UnsupportedSchemaVersion(str(payload.get("schema_version")))
        provenance_data = payload["provenance"]
        trace_data = payload.get("response_trace")
        diagnostics_data = payload.get("diagnostics")
        evidence_data = payload.get("evidence")
        diagnostics = None
        if diagnostics_data is not None:
            diagnostics = Diagnostics(
                _diagnostic_from_dict(diagnostics_data["subharmonic_response"]),
                _diagnostic_from_dict(diagnostics_data["evidence_limitations"]),
            )
        evidence = None if evidence_data is None else EvidenceUnavailable(**evidence_data)
        return cls(
            status=ValidationStatus(payload["status"]),
            provenance=Provenance(**provenance_data),
            response_trace=None
            if trace_data is None
            else ResponseTrace(trace_data["periods"], tuple(trace_data["values"])),
            diagnostics=diagnostics,
            failure_modes=tuple(payload["failure_modes"]),
            reproducibility=dict(payload["reproducibility"]),
            evidence=evidence,
        )

    @staticmethod
    def _diagnostic_dict(diagnostic: Diagnostic) -> dict[str, Any]:
        return {"status": diagnostic.status, "metric": diagnostic.metric, "reason": diagnostic.reason}


def _diagnostic_from_dict(value: dict[str, Any]) -> Diagnostic:
    return Diagnostic(value["status"], value["metric"], value["reason"])