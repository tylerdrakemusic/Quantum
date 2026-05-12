"""Execution policy helpers for benchmark/cache schedules and observability."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_POLICY_FILE = Path(__file__).resolve().parent.parent / "config" / "execution_policy.json"


class PolicyConfigError(RuntimeError):
    """Raised when execution policy config is missing or malformed."""


def load_policy_config() -> dict:
    """Load and validate execution policy config from src/config/execution_policy.json."""
    if not _POLICY_FILE.exists():
        raise PolicyConfigError(f"Missing execution policy config: {_POLICY_FILE}")

    with open(_POLICY_FILE, encoding="utf-8") as fh:
        data = json.load(fh)

    if "schedules" not in data or "qpu_caps_seconds" not in data:
        raise PolicyConfigError("execution_policy.json missing required keys")
    return data


def policy_schedule(policy_id: str) -> dict:
    """Return schedule payload for a policy id."""
    config = load_policy_config()
    schedules = config.get("schedules", {})
    if policy_id not in schedules:
        raise PolicyConfigError(f"Unknown policy id: {policy_id}")
    return schedules[policy_id]


def policy_qpu_cap_seconds(policy_id: str, default: int) -> int:
    """Return configured QPU cap for a policy id, with fallback default."""
    try:
        config = load_policy_config()
        cap = int(config.get("qpu_caps_seconds", {}).get(policy_id, default))
        return cap if cap > 0 else default
    except (PolicyConfigError, TypeError, ValueError):
        return default


def next_run_utc(policy_id: str, now_utc: datetime | None = None) -> datetime:
    """Compute next monthly run timestamp in UTC for a policy id."""
    schedule = policy_schedule(policy_id)
    day = int(schedule.get("day_of_month", 1))
    hour = int(schedule.get("hour", 0))
    minute = int(schedule.get("minute", 0))

    now = now_utc or datetime.now(timezone.utc)
    year = now.year
    month = now.month

    candidate = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    if candidate <= now:
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
        candidate = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    return candidate


def next_run_iso(policy_id: str, now_utc: datetime | None = None) -> str:
    """Return next run UTC timestamp in ISO-like Z format."""
    return next_run_utc(policy_id, now_utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def schedule_label(policy_id: str) -> str:
    """Return human-readable monthly schedule summary in UTC."""
    schedule = policy_schedule(policy_id)
    return (
        f"Day {int(schedule.get('day_of_month', 1))} @ "
        f"{int(schedule.get('hour', 0)):02d}:{int(schedule.get('minute', 0)):02d} UTC"
    )
