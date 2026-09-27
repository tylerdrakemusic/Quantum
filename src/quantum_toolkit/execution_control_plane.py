"""Provider-neutral lifecycle control for benchmark execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any, Callable, Mapping, Protocol

from .benchmark_provenance import adapt_result, persist_manifest
from .benchmark_replay import persist_replay, replay_local
from .execution_planner import AvailabilitySnapshot, NormalizedRequest, PlannerStatus, plan_execution

SUPPORTED_FAMILIES = frozenset({"shor", "vqe", "qaoa", "qec", "quantum_kernel"})


class DecisionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PERMITTED = "permitted"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"
    DEFERRED = "deferred"


class LifecycleState(StrEnum):
    RECEIVED = "received"
    NORMALIZED = "normalized"
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    DEFERRED = "deferred"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ControlPlaneRequest:
    family: str
    normalized: NormalizedRequest
    parameters: Mapping[str, Any]

    @property
    def request_id(self) -> str:
        return self.normalized.request_id

    @property
    def schema_version(self) -> str:
        return self.normalized.schema_version

    def to_dict(self) -> dict[str, Any]:
        return {"family": self.family, **self.normalized.to_dict(), "parameters": dict(self.parameters)}


@dataclass(frozen=True)
class GateSnapshot:
    health: bool
    quota: bool
    credential_safe: bool
    retry: bool
    schedule: bool
    policy: bool
    approval: bool


@dataclass(frozen=True)
class Decision:
    status: DecisionStatus
    reason_codes: tuple[str, ...]
    provider_id: str | None = None


@dataclass(frozen=True)
class LifecycleResult:
    state: LifecycleState
    decision: Decision
    evidence_references: tuple[str, ...]


class Submitter(Protocol):
    def __call__(self, payload: dict[str, object]) -> str: ...


def _ensure_tables(conn: Any) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS benchmark_provenance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            identity_family TEXT NOT NULL,
            manifest_version TEXT NOT NULL,
            provenance_status TEXT NOT NULL,
            manifest_json TEXT NOT NULL,
            evidence_references_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS benchmark_replays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            family TEXT NOT NULL,
            outcome TEXT NOT NULL,
            seed INTEGER NOT NULL,
            tolerance_version TEXT NOT NULL,
            replay_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS execution_lifecycle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            family TEXT NOT NULL,
            state TEXT NOT NULL,
            decision_status TEXT NOT NULL,
            reason_codes_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS execution_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            family TEXT NOT NULL,
            status TEXT NOT NULL,
            reason_codes_json TEXT NOT NULL,
            provider_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS execution_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            reference TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )


def _record_lifecycle(conn: Any, request: ControlPlaneRequest, state: LifecycleState, decision: Decision) -> None:
    conn.execute(
        "INSERT INTO execution_lifecycle (request_id, family, state, decision_status, reason_codes_json) VALUES (?, ?, ?, ?, ?)",
        (request.request_id, request.family, state.value, decision.status.value, json.dumps(decision.reason_codes)),
    )


def _record_evidence(conn: Any, request: ControlPlaneRequest, references: tuple[str, ...]) -> None:
    conn.executemany(
        "INSERT INTO execution_evidence (request_id, evidence_type, reference) VALUES (?, ?, ?)",
        [(request.request_id, "artifact", reference) for reference in references],
    )


def _record_decision(conn: Any, request: ControlPlaneRequest, decision: Decision) -> None:
    conn.execute(
        "INSERT INTO execution_decisions (request_id, family, status, reason_codes_json, provider_id) VALUES (?, ?, ?, ?, ?)",
        (request.request_id, request.family, decision.status.value, json.dumps(decision.reason_codes), decision.provider_id),
    )


class ControlPlane:
    """Normalize requests, evaluate gates, and run injected simulator callbacks."""

    def normalize(self, family: str, payload: Mapping[str, Any]) -> ControlPlaneRequest:
        if family not in SUPPORTED_FAMILIES:
            raise ValueError(f"unsupported benchmark family: {family}")
        normalized = NormalizedRequest.from_dict(
            {"schema_version": "1.0", **{key: value for key, value in payload.items() if key != "parameters"}}
        )
        parameters = payload.get("parameters", {})
        if not isinstance(parameters, Mapping):
            raise ValueError("parameters must be an object")
        return ControlPlaneRequest(family, normalized, dict(parameters))

    def plan_hardware(self, request: ControlPlaneRequest, gates: GateSnapshot, provider_id: str | None = None) -> Decision:
        failures = tuple(name for name in ("health", "quota", "credential_safe", "retry", "schedule", "policy") if not getattr(gates, name))
        if "health" in failures or "credential_safe" in failures or "policy" in failures:
            decision = Decision(DecisionStatus.BLOCKED, failures, provider_id)
        elif failures:
            decision = Decision(DecisionStatus.DEFERRED, failures, provider_id)
        elif not gates.approval:
            decision = Decision(DecisionStatus.APPROVAL_REQUIRED, ("approval",), provider_id)
        else:
            decision = Decision(DecisionStatus.PERMITTED, (), provider_id)
        return decision

    def classify_from_snapshots(
        self,
        request: ControlPlaneRequest,
        snapshots: tuple[AvailabilitySnapshot, ...],
        gates: GateSnapshot,
        *,
        now_utc: str,
        approved: bool = False,
    ) -> Decision:
        plan = plan_execution(request.normalized, snapshots, now_utc=now_utc, approved=approved)
        if plan.status is PlannerStatus.DEFERRED:
            return Decision(DecisionStatus.DEFERRED, plan.reason_codes, plan.selected_provider_id)
        if plan.status in {PlannerStatus.BLOCKED, PlannerStatus.FALLBACK_RECOMMENDED}:
            return Decision(DecisionStatus.BLOCKED, plan.reason_codes, plan.selected_provider_id)
        if plan.status is PlannerStatus.RUNNABLE_SIMULATOR:
            return Decision(DecisionStatus.SUCCEEDED, plan.reason_codes, plan.selected_provider_id)
        return self.plan_hardware(request, gates, plan.selected_provider_id)

    def execute_simulator(
        self,
        request: ControlPlaneRequest,
        *,
        execute: Callable[[int], Mapping[str, Any]],
        seed: int,
        conn: Any,
    ) -> LifecycleResult:
        _ensure_tables(conn)
        received = Decision(DecisionStatus.SUCCEEDED, ("simulator_selected",))
        for state in (LifecycleState.RECEIVED, LifecycleState.NORMALIZED, LifecycleState.PLANNED, LifecycleState.RUNNING):
            _record_lifecycle(conn, request, state, received)
        replay = replay_local(request.family, seed=seed, execute=execute)
        manifest = adapt_result(
            request.family,
            replay,
            run_id=request.request_id,
            backend_name="simulator",
            configuration={"seed": seed, "request": _redact(request.to_dict())},
            evidence_references=(f"replay:{request.request_id}", f"provenance:{request.request_id}"),
        )
        persist_manifest(conn, manifest)
        persist_replay(conn, replay, run_id=request.request_id)
        references = (f"provenance:{request.request_id}", f"replay:{request.request_id}")
        _record_evidence(conn, request, references)
        decision = Decision(DecisionStatus.SUCCEEDED if replay["outcome"] == "pass" else DecisionStatus.BLOCKED, ("simulator_completed",) if replay["outcome"] == "pass" else ("simulator_failed",))
        _record_decision(conn, request, decision)
        final_state = LifecycleState.COMPLETED if decision.status is DecisionStatus.SUCCEEDED else LifecycleState.BLOCKED
        _record_lifecycle(conn, request, final_state, decision)
        conn.commit()
        return LifecycleResult(final_state, decision, references)


class _GuardedAdapter:
    provider: str

    def __init__(self, submit: Submitter) -> None:
        self._submit = submit

    def submit(self, request: ControlPlaneRequest, decision: Decision) -> str:
        if decision.status is not DecisionStatus.PERMITTED:
            raise PermissionError("hardware submission requires a permitted decision")
        payload = {"request_id": request.request_id, "family": request.family}
        return str(self._submit(payload))


class IBMQuantumAdapter(_GuardedAdapter):
    provider = "ibm"


class AmazonBraketAdapter(_GuardedAdapter):
    provider = "braket"


_SECRET_FIELDS = {"api_key", "apikey", "token", "password", "secret", "credential"}


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _SECRET_FIELDS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value