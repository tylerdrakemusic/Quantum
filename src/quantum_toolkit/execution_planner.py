"""Provider-neutral, side-effect-free execution planning contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping, Sequence


class PlannerContractError(ValueError):
    """Raised when a normalized planner request or snapshot is invalid."""


class PlannerStatus(StrEnum):
    RUNNABLE_SIMULATOR = "runnable_simulator"
    RUNNABLE_HARDWARE_PLAN = "runnable_hardware_plan"
    FALLBACK_RECOMMENDED = "fallback_recommended"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"
    DEFERRED = "deferred"


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlannerContractError(f"{field} must be a non-empty string")
    return value.strip()


def _require_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PlannerContractError(f"{field} must be a positive integer")
    return value


def _parse_utc(value: Any, field: str) -> datetime:
    text = _require_string(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlannerContractError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise PlannerContractError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class ScheduleWindow:
    start_utc: datetime
    end_utc: datetime

    def __post_init__(self) -> None:
        if self.start_utc.tzinfo is None or self.end_utc.tzinfo is None:
            raise PlannerContractError("schedule window timestamps must include a timezone")
        if self.end_utc <= self.start_utc:
            raise PlannerContractError("schedule window end must be after start")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ScheduleWindow":
        return cls(
            start_utc=_parse_utc(value.get("start_utc"), "schedule_window.start_utc"),
            end_utc=_parse_utc(value.get("end_utc"), "schedule_window.end_utc"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "start_utc": self.start_utc.isoformat().replace("+00:00", "Z"),
            "end_utc": self.end_utc.isoformat().replace("+00:00", "Z"),
        }


@dataclass(frozen=True)
class NormalizedRequest:
    schema_version: str
    request_id: str
    qubits: int
    depth: int
    shots: int
    estimated_duration_seconds: float
    requires_hardware: bool
    allow_simulator_fallback: bool
    hardware_approval_required: bool
    schedule_window: ScheduleWindow | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NormalizedRequest":
        if not isinstance(value, Mapping):
            raise PlannerContractError("request must be an object")
        schema_version = _require_string(value.get("schema_version"), "schema_version")
        if schema_version != "1.0":
            raise PlannerContractError("schema_version must be 1.0")
        required = {
            "schema_version", "request_id", "qubits", "depth", "shots",
            "estimated_duration_seconds", "requires_hardware",
            "allow_simulator_fallback", "hardware_approval_required",
        }
        unknown = set(value) - required - {"schedule_window"}
        if unknown:
            raise PlannerContractError(f"unknown request fields: {sorted(unknown)}")
        duration = value.get("estimated_duration_seconds")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration < 0:
            raise PlannerContractError("estimated_duration_seconds must be non-negative")
        booleans = ("requires_hardware", "allow_simulator_fallback", "hardware_approval_required")
        for field in booleans:
            if not isinstance(value.get(field), bool):
                raise PlannerContractError(f"{field} must be boolean")
        window = value.get("schedule_window")
        if window is not None and not isinstance(window, Mapping):
            raise PlannerContractError("schedule_window must be an object")
        return cls(
            schema_version=schema_version,
            request_id=_require_string(value.get("request_id"), "request_id"),
            qubits=_require_positive_int(value.get("qubits"), "qubits"),
            depth=_require_positive_int(value.get("depth"), "depth"),
            shots=_require_positive_int(value.get("shots"), "shots"),
            estimated_duration_seconds=float(duration),
            requires_hardware=value["requires_hardware"],
            allow_simulator_fallback=value["allow_simulator_fallback"],
            hardware_approval_required=value["hardware_approval_required"],
            schedule_window=ScheduleWindow.from_dict(window) if window is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "qubits": self.qubits,
            "depth": self.depth,
            "shots": self.shots,
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "requires_hardware": self.requires_hardware,
            "allow_simulator_fallback": self.allow_simulator_fallback,
            "hardware_approval_required": self.hardware_approval_required,
        }
        if self.schedule_window is not None:
            result["schedule_window"] = self.schedule_window.to_dict()
        return result


@dataclass(frozen=True)
class AvailabilitySnapshot:
    provider_id: str
    provider: str
    execution_mode: str
    available: bool
    observed_at: datetime
    freshness_seconds: int
    max_qubits: int
    quota_remaining_seconds: float

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AvailabilitySnapshot":
        if not isinstance(value, Mapping):
            raise PlannerContractError("availability snapshot must be an object")
        allowed = {
            "provider_id", "provider", "execution_mode", "available", "observed_at",
            "freshness_seconds", "max_qubits", "quota_remaining_seconds",
        }
        unknown = set(value) - allowed
        if unknown:
            raise PlannerContractError(f"unknown snapshot fields: {sorted(unknown)}")
        mode = _require_string(value.get("execution_mode"), "execution_mode")
        if mode not in {"hardware", "simulator"}:
            raise PlannerContractError("execution_mode must be hardware or simulator")
        freshness = value.get("freshness_seconds")
        if isinstance(freshness, bool) or not isinstance(freshness, int) or freshness <= 0:
            raise PlannerContractError("freshness_seconds must be a positive integer")
        max_qubits = _require_positive_int(value.get("max_qubits"), "max_qubits")
        quota = value.get("quota_remaining_seconds")
        if isinstance(quota, bool) or not isinstance(quota, (int, float)) or quota < 0:
            raise PlannerContractError("quota_remaining_seconds must be non-negative")
        if not isinstance(value.get("available"), bool):
            raise PlannerContractError("available must be boolean")
        return cls(
            provider_id=_require_string(value.get("provider_id"), "provider_id"),
            provider=_require_string(value.get("provider"), "provider"),
            execution_mode=mode,
            available=value["available"],
            observed_at=_parse_utc(value.get("observed_at"), "observed_at"),
            freshness_seconds=freshness,
            max_qubits=max_qubits,
            quota_remaining_seconds=float(quota),
        )


@dataclass(frozen=True)
class PlanResult:
    status: PlannerStatus
    selected_provider_id: str | None
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "selected_provider_id": self.selected_provider_id,
            "reason_codes": list(self.reason_codes),
        }


def _as_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise PlannerContractError("now_utc must include a timezone")
        return value.astimezone(timezone.utc)
    return _parse_utc(value, "now_utc")


def plan_execution(
    request: NormalizedRequest,
    snapshots: Sequence[AvailabilitySnapshot],
    *,
    now_utc: str | datetime,
    approved: bool = False,
) -> PlanResult:
    """Evaluate a normalized request without contacting or mutating a provider."""
    now = _as_utc(now_utc)
    if request.schedule_window is not None:
        if not request.schedule_window.start_utc <= now <= request.schedule_window.end_utc:
            return PlanResult(PlannerStatus.DEFERRED, None, ("outside_schedule_window",))

    normalized = sorted(snapshots, key=lambda item: item.provider_id)
    stale_hardware = False
    eligible_hardware: list[AvailabilitySnapshot] = []
    eligible_simulators: list[AvailabilitySnapshot] = []
    for snapshot in normalized:
        age = (now - snapshot.observed_at).total_seconds()
        fresh = 0 <= age <= snapshot.freshness_seconds
        if snapshot.execution_mode == "hardware" and not fresh:
            stale_hardware = True
        if not snapshot.available or not fresh or snapshot.max_qubits < request.qubits:
            continue
        if snapshot.execution_mode == "hardware":
            if snapshot.quota_remaining_seconds >= request.estimated_duration_seconds:
                eligible_hardware.append(snapshot)
        else:
            eligible_simulators.append(snapshot)

    if eligible_hardware:
        selected = eligible_hardware[0]
        if request.hardware_approval_required and not approved:
            return PlanResult(
                PlannerStatus.APPROVAL_REQUIRED,
                selected.provider_id,
                ("hardware_approval_required",),
            )
        return PlanResult(
            PlannerStatus.RUNNABLE_HARDWARE_PLAN,
            selected.provider_id,
            ("hardware_capability_and_quota_fit",),
        )

    reasons: list[str] = []
    if stale_hardware:
        reasons.append("stale_hardware_snapshot")
    if request.requires_hardware:
        reasons.append("hardware_required")
        return PlanResult(PlannerStatus.BLOCKED, None, tuple(reasons or ["no_hardware_fit"]))
    if eligible_simulators:
        if stale_hardware:
            reasons.append("hardware_fallback_allowed")
            return PlanResult(
                PlannerStatus.FALLBACK_RECOMMENDED,
                eligible_simulators[0].provider_id,
                tuple(reasons),
            )
        return PlanResult(
            PlannerStatus.RUNNABLE_SIMULATOR,
            eligible_simulators[0].provider_id,
            ("simulator_capability_fit",),
        )
    return PlanResult(PlannerStatus.BLOCKED, None, tuple(reasons or ["no_provider_fit"]))