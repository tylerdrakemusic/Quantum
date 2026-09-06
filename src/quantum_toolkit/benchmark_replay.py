"""Seeded replay, comparison, and IBM Runtime safety helpers."""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Callable, Mapping

TOLERANCE_VERSION = "2026-09-05"
SUPPORTED_FAMILIES = frozenset({"shor", "vqe", "qaoa", "qec", "quantum_kernel"})
TOLERANCES: dict[str, dict[str, dict[str, float]]] = {
    family: {"default": {"absolute": 1e-6, "relative": 1e-6}}
    for family in SUPPORTED_FAMILIES
}
TOLERANCES["vqe"] = {"energy": {"absolute": 0.02, "relative": 0.02}}
TOLERANCES["qaoa"] = {"approximation_ratio": {"absolute": 0.05, "relative": 0.05}}

_SECRET_KEYS = {"api_key", "apikey", "token", "password", "secret", "credential"}


def _check_family(family: str) -> None:
    if family not in SUPPORTED_FAMILIES:
        raise ValueError(f"unsupported benchmark family: {family}")


def compare_metrics(
    family: str,
    *,
    expected: Mapping[str, float],
    actual: Mapping[str, float],
) -> dict[str, Any]:
    """Compare family metrics and retain the exact tolerance set used."""
    _check_family(family)
    metric_results: dict[str, dict[str, float | bool]] = {}
    passed = True
    for name, expected_value in expected.items():
        if name not in actual:
            passed = False
            metric_results[name] = {"available": False, "passed": False}
            continue
        actual_value = float(actual[name])
        absolute_error = abs(actual_value - float(expected_value))
        relative_error = absolute_error / max(abs(float(expected_value)), 1e-12)
        tolerance = TOLERANCES[family].get(name) or TOLERANCES[family].get(
            "default", {"absolute": 1e-6, "relative": 1e-6}
        )
        metric_passed = (
            absolute_error <= tolerance["absolute"]
            or relative_error <= tolerance["relative"]
        )
        passed = passed and metric_passed
        metric_results[name] = {
            "available": True,
            "absolute_error": absolute_error,
            "relative_error": relative_error,
            "absolute_tolerance": tolerance["absolute"],
            "relative_tolerance": tolerance["relative"],
            "passed": metric_passed,
        }
    return {
        "family": family,
        "status": "pass" if passed else "tolerance_failure",
        "tolerance_version": TOLERANCE_VERSION,
        "tolerances": deepcopy(TOLERANCES[family]),
        "metrics": metric_results,
    }


def replay_local(
    family: str,
    *,
    seed: int,
    execute: Callable[[int], Mapping[str, Any]],
) -> dict[str, Any]:
    """Run a seeded local simulator callback and classify its outcome."""
    _check_family(family)
    try:
        result = dict(execute(seed))
    except Exception as exc:  # noqa: BLE001
        return {
            "family": family,
            "seed": seed,
            "outcome": "execution_failure",
            "error_type": type(exc).__name__,
            "tolerance_version": TOLERANCE_VERSION,
        }
    outcome = str(result.pop("status", result.pop("outcome", "pass")))
    if outcome not in {"pass", "tolerance_failure", "unavailable", "execution_failure", "nondeterministic"}:
        outcome = "execution_failure"
    return {
        "family": family,
        "seed": seed,
        "outcome": outcome,
        "tolerance_version": TOLERANCE_VERSION,
        "result": result,
    }


def capture_runtime_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Capture operational Runtime metadata while removing credential values."""
    def redact(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): ("[REDACTED]" if str(key).lower() in _SECRET_KEYS else redact(item))
                for key, item in value.items()
                if str(key).lower() not in _SECRET_KEYS
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    captured = redact(result)
    captured["credential_safe"] = True
    return captured


def resubmission_decision(
    captured: Mapping[str, Any], *, approved: bool, quota_remaining_seconds: float
) -> dict[str, Any]:
    """Return an observable, bounded decision without submitting a job."""
    if quota_remaining_seconds <= 0:
        status = "quota_blocked"
    elif not approved:
        status = "approval_required"
    elif captured.get("execution", {}).get("status") != "failed":
        status = "not_eligible"
    elif captured.get("execution", {}).get("retry_count", 0) > 0:
        status = "retry_limit_reached"
    else:
        status = "approved"
    return {
        "status": status,
        "quota_remaining_seconds": quota_remaining_seconds,
        "automatic_submission": False,
        "credential_safe": bool(captured.get("credential_safe", False)),
    }


def resubmit_runtime_job(
    captured: Mapping[str, Any],
    *,
    approved: bool,
    quota_remaining_seconds: float,
    submit: Callable[[], str],
) -> dict[str, Any]:
    """Submit one approved failed job through an injected Runtime client."""
    decision = resubmission_decision(
        captured, approved=approved, quota_remaining_seconds=quota_remaining_seconds
    )
    if decision["status"] != "approved":
        return {"status": decision["status"], "attempt": 0}
    new_job_id = submit()
    return {"status": "submitted", "new_job_id": str(new_job_id), "attempt": 1}


def persist_replay(conn: Any, replay: Mapping[str, Any], *, run_id: str) -> int:
    """Persist a normalized replay record without touching legacy tables."""
    family = str(replay["family"])
    _check_family(family)
    cursor = conn.execute(
        """INSERT INTO benchmark_replays
           (run_id, family, outcome, seed, tolerance_version, replay_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            run_id,
            family,
            str(replay["outcome"]),
            int(replay["seed"]),
            str(replay["tolerance_version"]),
            json.dumps(dict(replay), sort_keys=True),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)