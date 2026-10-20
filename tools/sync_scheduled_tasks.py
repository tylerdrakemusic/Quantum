"""Build or register Windows scheduled tasks from execution policy."""

from __future__ import annotations

import argparse
import csv
import getpass
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_POLICY_FILE = _ROOT / "src" / "config" / "execution_policy.json"
_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"
_MANAGED_TASK_DESCRIPTION = "Managed by Quantum execution_policy.json."
ET.register_namespace("", _NAMESPACE)


def _tag(name: str) -> str:
    return f"{{{_NAMESPACE}}}{name}"


def _is_windows() -> bool:
    return os.name == "nt"


def _next_start_boundary(schedule: dict[str, Any], now_utc: datetime) -> datetime:
    now = now_utc.astimezone(timezone.utc)
    if "day_of_month" in schedule:
        day = int(schedule["day_of_month"])
        candidate = datetime(
            now.year, now.month, day, int(schedule["hour"]), int(schedule["minute"]),
            tzinfo=timezone.utc,
        )
        if candidate <= now:
            year, month = now.year + (now.month == 12), now.month % 12 + 1
            candidate = datetime(
                year, month, day, int(schedule["hour"]), int(schedule["minute"]),
                tzinfo=timezone.utc,
            )
        return candidate

    if schedule.get("schedule") == "daily":
        hour, minute = (int(part) for part in schedule["time_utc"].split(":"))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return candidate if candidate > now else candidate + timedelta(days=1)

    raise ValueError("schedule must define day_of_month or schedule='daily'")


def build_task_definition(
    *,
    task_name: str,
    schedule: dict[str, Any],
    action: dict[str, Any],
    repository_root: Path,
    now_utc: datetime,
    task_name_suffix: str = "",
) -> tuple[str, str]:
    """Return the effective task name and UTC-based Task Scheduler XML."""
    if task_name_suffix and not re.fullmatch(r"[A-Za-z0-9_-]+", task_name_suffix):
        raise ValueError("task name suffix may contain only letters, digits, '_' and '-'")
    effective_name = f"{task_name}{task_name_suffix}"
    start = _next_start_boundary(schedule, now_utc)

    root = ET.Element(_tag("Task"), {"version": "1.3"})
    registration = ET.SubElement(root, _tag("RegistrationInfo"))
    ET.SubElement(registration, _tag("Description")).text = _MANAGED_TASK_DESCRIPTION
    triggers = ET.SubElement(root, _tag("Triggers"))
    trigger = ET.SubElement(triggers, _tag("CalendarTrigger"))
    ET.SubElement(trigger, _tag("StartBoundary")).text = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    ET.SubElement(trigger, _tag("Enabled")).text = "true"

    if "day_of_month" in schedule:
        recurrence = ET.SubElement(trigger, _tag("ScheduleByMonth"))
        days = ET.SubElement(recurrence, _tag("DaysOfMonth"))
        ET.SubElement(days, _tag("Day")).text = str(int(schedule["day_of_month"]))
        months = ET.SubElement(recurrence, _tag("Months"))
        for month in (
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ):
            ET.SubElement(months, _tag(month))
    else:
        recurrence = ET.SubElement(trigger, _tag("ScheduleByDay"))
        ET.SubElement(recurrence, _tag("DaysInterval")).text = "1"

    principals = ET.SubElement(root, _tag("Principals"))
    principal = ET.SubElement(principals, _tag("Principal"), {"id": "Author"})
    domain = os.environ.get("USERDOMAIN", "")
    user = getpass.getuser()
    ET.SubElement(principal, _tag("UserId")).text = f"{domain}\\{user}" if domain else user
    ET.SubElement(principal, _tag("LogonType")).text = str(action.get("logon_type", "InteractiveToken"))
    ET.SubElement(principal, _tag("RunLevel")).text = "LeastPrivilege"

    settings = ET.SubElement(root, _tag("Settings"))
    ET.SubElement(settings, _tag("MultipleInstancesPolicy")).text = str(
        action.get("multiple_instances", "IgnoreNew")
    )
    ET.SubElement(settings, _tag("StartWhenAvailable")).text = str(
        bool(action.get("start_when_available", False))
    ).lower()
    ET.SubElement(settings, _tag("ExecutionTimeLimit")).text = (
        f"PT{int(action['execution_time_limit_seconds'])}S"
    )
    ET.SubElement(settings, _tag("Enabled")).text = "true"
    ET.SubElement(settings, _tag("AllowStartOnDemand")).text = "true"
    ET.SubElement(settings, _tag("DisallowStartIfOnBatteries")).text = "false"
    ET.SubElement(settings, _tag("StopIfGoingOnBatteries")).text = "false"

    actions = ET.SubElement(root, _tag("Actions"), {"Context": "Author"})
    exec_action = ET.SubElement(actions, _tag("Exec"))
    ET.SubElement(exec_action, _tag("Command")).text = str(action["executable"])
    arguments = [str(argument) for argument in action.get("arguments", [])]
    ET.SubElement(exec_action, _tag("Arguments")).text = subprocess.list2cmdline(arguments)
    working_directory = Path(str(action.get("working_directory", ".")))
    if not working_directory.is_absolute():
        working_directory = repository_root / working_directory
    ET.SubElement(exec_action, _tag("WorkingDirectory")).text = str(working_directory.resolve())

    xml_text = ET.tostring(root, encoding="unicode", xml_declaration=True)
    return effective_name, xml_text


def register_task(task_name: str, xml_text: str) -> None:
    """Register one task using schtasks.exe and a temporary UTF-16 XML file."""
    if not _is_windows():
        raise RuntimeError("scheduled-task registration is supported only on Windows")
    try:
        inventory = subprocess.run(
            ["schtasks.exe", "/Query", "/FO", "CSV", "/NH"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        task_paths = {
            "\\" + row[0].lstrip("\\")
            for row in csv.reader(io.StringIO(inventory.stdout))
            if row
        }
    except (OSError, subprocess.CalledProcessError, csv.Error) as exc:
        raise RuntimeError(
            "Unable to inspect scheduled tasks; refusing to register tasks."
        ) from exc

    target_path = "\\" + task_name.lstrip("\\")
    if target_path in task_paths:
        try:
            existing = subprocess.run(
                ["schtasks.exe", "/Query", "/TN", task_name, "/XML"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            existing_root = ET.fromstring(existing.stdout)
        except (OSError, subprocess.CalledProcessError, ET.ParseError) as exc:
            raise RuntimeError(
                f"Unable to verify scheduled task {task_name!r}; refusing to replace it."
            ) from exc
        description = existing_root.findtext(
            f"{_tag('RegistrationInfo')}/{_tag('Description')}",
            default="",
        )
        if description != _MANAGED_TASK_DESCRIPTION:
            raise RuntimeError(
                f"Scheduled task {task_name!r} is not managed by Quantum; refusing to replace it."
            )

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-16", suffix=".xml", delete=False,
    ) as task_file:
        task_file.write(xml_text.replace("encoding='utf-8'", "encoding='UTF-16'", 1))
        xml_path = task_file.name
    try:
        subprocess.run(
            ["schtasks.exe", "/Create", "/TN", task_name, "/XML", xml_path, "/F"],
            check=True,
        )
    finally:
        Path(xml_path).unlink(missing_ok=True)


def sync_policy_tasks(
    policy: dict[str, Any],
    repository_root: Path,
    *,
    now_utc: datetime,
    apply: bool = False,
    task_name_suffix: str = "",
    policy_ids: set[str] | None = None,
) -> list[tuple[str, str]]:
    """Build configured task XML and optionally register each configured task."""
    if policy.get("timezone") != "UTC":
        raise ValueError("execution policy timezone must be UTC")
    schedules = policy.get("schedules", {})
    actions = policy.get("scheduled_task_actions", {})
    if policy_ids is not None:
        unknown_policy_ids = policy_ids - actions.keys()
        if unknown_policy_ids:
            raise ValueError(f"No scheduled task actions configured for: {sorted(unknown_policy_ids)}")
    definitions: list[tuple[str, str]] = []
    for policy_id, action in actions.items():
        if policy_ids is not None and policy_id not in policy_ids:
            continue
        schedule = schedules.get(policy_id)
        if not isinstance(schedule, dict):
            raise ValueError(f"No schedule configured for task policy {policy_id}")
        task_name, xml_text = build_task_definition(
            task_name=str(schedule["task_name"]),
            schedule=schedule,
            action=action,
            repository_root=repository_root,
            now_utc=now_utc,
            task_name_suffix=task_name_suffix,
        )
        definitions.append((task_name, xml_text))
        if apply:
            register_task(task_name, xml_text)
    return definitions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-file", type=Path, default=_POLICY_FILE)
    parser.add_argument("--apply", action="store_true", help="Register tasks (default: print dry-run XML).")
    parser.add_argument("--task-name-suffix", default="", help="Append a local-only suffix to task names.")
    parser.add_argument("--policy-id", action="append", help="Synchronize only this policy id; may be repeated.")
    args = parser.parse_args(argv)

    policy = json.loads(args.policy_file.read_text(encoding="utf-8"))
    definitions = sync_policy_tasks(
        policy,
        args.policy_file.resolve().parents[2],
        now_utc=datetime.now(timezone.utc),
        apply=args.apply,
        task_name_suffix=args.task_name_suffix,
        policy_ids=set(args.policy_id) if args.policy_id else None,
    )
    mode = "Registered" if args.apply else "Dry run"
    for task_name, xml_text in definitions:
        print(f"{mode}: {task_name}")
        if not args.apply:
            print(xml_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())