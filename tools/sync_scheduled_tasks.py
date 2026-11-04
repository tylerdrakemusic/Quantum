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
_ADOPTABLE_TASK_NAMES = frozenset({"QuantumCacheFill_Monthly", "ShorsMonthlyBench"})
ET.register_namespace("", _NAMESPACE)


def _tag(name: str) -> str:
    return f"{{{_NAMESPACE}}}{name}"


def _validate_adoption_options(
    adopt_existing_task_names: set[str] | None,
    backup_directory: Path | None,
    repository_root: Path | None,
) -> tuple[frozenset[str], Path | None]:
    if adopt_existing_task_names is None:
        if backup_directory is not None:
            raise ValueError("a backup directory requires an explicit task adoption allowlist")
        return frozenset(), None

    names = frozenset(adopt_existing_task_names)
    if not names or names - _ADOPTABLE_TASK_NAMES:
        raise ValueError("task adoption allowlist may contain only the approved exact task names")
    if backup_directory is None:
        raise ValueError("task adoption requires an ignored backup directory under repository tmp/")

    root = (repository_root or _ROOT).resolve()
    tmp_root = (root / "tmp").resolve()
    candidate = backup_directory if backup_directory.is_absolute() else root / backup_directory
    try:
        backup_path = candidate.resolve(strict=True)
        relative_to_tmp = backup_path.relative_to(tmp_root)
    except (OSError, ValueError) as exc:
        raise ValueError("backup directory must exist under repository tmp/") from exc
    if backup_path == tmp_root or not relative_to_tmp.parts or not backup_path.is_dir():
        raise ValueError("backup directory must be a directory beneath repository tmp/")

    relative_path = backup_path.relative_to(root).as_posix()
    try:
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", relative_path],
            cwd=str(root),
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise ValueError("unable to verify that the backup directory is ignored") from exc
    if ignored.returncode != 0:
        raise ValueError("backup directory must be ignored by Git")
    return names, backup_path


def _scheduled_task_paths() -> set[str]:
    try:
        inventory = subprocess.run(
            ["schtasks.exe", "/Query", "/FO", "CSV", "/NH"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "\\" + row[0].lstrip("\\")
            for row in csv.reader(io.StringIO(inventory.stdout))
            if row
        }
    except (OSError, subprocess.CalledProcessError, csv.Error) as exc:
        raise RuntimeError(
            "Unable to inspect scheduled tasks; refusing to register tasks."
        ) from exc


def _parse_task_xml(xml_data: bytes) -> ET.Element:
    xml_text = xml_data.decode("utf-8-sig")
    if xml_text.startswith("<?xml") and xml_text[5:6].isspace():
        declaration_end = xml_text.find("?>")
        if declaration_end < 0:
            raise ET.ParseError("Task Scheduler returned an unterminated XML declaration")
        xml_text = xml_text[declaration_end + 2:]
    return ET.fromstring(xml_text)


def _export_scheduled_task(task_name: str) -> tuple[bytes, ET.Element]:
    try:
        exported = subprocess.run(
            ["schtasks.exe", "/Query", "/TN", task_name, "/XML"],
            check=True,
            capture_output=True,
        )
        xml_data = exported.stdout
        if isinstance(xml_data, str):
            xml_data = xml_data.encode("utf-8")
        if not isinstance(xml_data, bytes):
            raise ET.ParseError("Task Scheduler returned no XML data")
        return xml_data, _parse_task_xml(xml_data)
    except (OSError, subprocess.CalledProcessError, ET.ParseError, TypeError) as exc:
        raise RuntimeError(
            f"Unable to export and verify scheduled task {task_name!r}; refusing to replace it."
        ) from exc


def _save_task_backup(task_name: str, xml_data: bytes, backup_directory: Path) -> Path:
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f"{task_name}_",
            suffix=".xml",
            dir=backup_directory,
            delete=False,
        ) as backup_file:
            backup_file.write(xml_data)
        return Path(backup_file.name)
    except OSError as exc:
        raise RuntimeError(
            f"Unable to back up scheduled task {task_name!r}; refusing to replace it."
        ) from exc


def _exec_action_signature(root: ET.Element) -> tuple[str, str, str] | None:
    actions = root.find(_tag("Actions"))
    if actions is None or len(actions) != 1 or actions[0].tag != _tag("Exec"):
        return None
    action = actions[0]
    command = action.findtext(_tag("Command"), default="").strip()
    arguments = action.findtext(_tag("Arguments"), default="").strip()
    working_directory = action.findtext(_tag("WorkingDirectory"), default="").strip()
    if not command or not working_directory:
        return None
    return (
        os.path.normcase(os.path.normpath(command)),
        arguments,
        os.path.normcase(os.path.normpath(working_directory)),
    )


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
    working_directory_root: Path | None = None,
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
        working_directory = (working_directory_root or repository_root) / working_directory
    ET.SubElement(exec_action, _tag("WorkingDirectory")).text = str(working_directory.resolve())

    xml_text = ET.tostring(root, encoding="unicode", xml_declaration=True)
    return effective_name, xml_text


def register_task(
    task_name: str,
    xml_text: str,
    *,
    adopt_existing_task_names: set[str] | None = None,
    backup_directory: Path | None = None,
    repository_root: Path | None = None,
    _prepared_backup_file: Path | None = None,
) -> None:
    """Register one task using schtasks.exe and a temporary UTF-16 XML file."""
    adoption_names, validated_backup_directory = _validate_adoption_options(
        adopt_existing_task_names,
        backup_directory,
        repository_root,
    )
    if _prepared_backup_file is not None and task_name not in adoption_names:
        raise ValueError("a pre-registered backup is valid only for an allowlisted task")
    if not _is_windows():
        raise RuntimeError("scheduled-task registration is supported only on Windows")
    task_paths = _scheduled_task_paths()
    target_path = "\\" + task_name.lstrip("\\")
    if _prepared_backup_file is not None:
        try:
            backup_path = _prepared_backup_file.resolve(strict=True)
            if (
                validated_backup_directory is None
                or backup_path.parent != validated_backup_directory
                or not backup_path.name.startswith(f"{task_name}_")
                or not backup_path.is_file()
            ):
                raise ValueError("backup file does not match the validated task backup directory")
            backup_bytes = backup_path.read_bytes()
            _parse_task_xml(backup_bytes)
            existing_xml, _ = _export_scheduled_task(task_name)
            if backup_bytes != existing_xml:
                raise ValueError("prepared backup does not match the current scheduled task export")
        except (OSError, ValueError, ET.ParseError, RuntimeError) as exc:
            raise RuntimeError(
                f"Unable to verify backup for scheduled task {task_name!r}; refusing to replace it."
            ) from exc
    if target_path in task_paths:
        if task_name in adoption_names:
            if _prepared_backup_file is None:
                existing_xml, _ = _export_scheduled_task(task_name)
                if validated_backup_directory is None:
                    raise RuntimeError(
                        f"Unable to back up scheduled task {task_name!r}; refusing to replace it."
                    )
                _save_task_backup(task_name, existing_xml, validated_backup_directory)
        else:
            _, existing_root = _export_scheduled_task(task_name)
            description = existing_root.findtext(
                f"{_tag('RegistrationInfo')}/{_tag('Description')}",
                default="",
            )
            if description != _MANAGED_TASK_DESCRIPTION:
                raise RuntimeError(
                    f"Scheduled task {task_name!r} is not managed by Quantum; refusing to replace it."
                    )
            expected_root = ET.fromstring(xml_text)
            if _exec_action_signature(existing_root) != _exec_action_signature(expected_root):
                raise RuntimeError(
                    f"Scheduled task {task_name!r} action does not match the generated Quantum runner; "
                    "refusing to replace it."
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
    adopt_existing_task_names: set[str] | None = None,
    backup_directory: Path | None = None,
    working_directory_root: Path | None = None,
) -> list[tuple[str, str]]:
    """Build configured task XML and optionally register each configured task."""
    if policy.get("timezone") != "UTC":
        raise ValueError("execution policy timezone must be UTC")
    if adopt_existing_task_names is None:
        if backup_directory is not None:
            raise ValueError("a backup directory requires an explicit task adoption allowlist")
        adoption_names = frozenset()
    else:
        adoption_names = frozenset(adopt_existing_task_names)
        if not adoption_names or adoption_names - _ADOPTABLE_TASK_NAMES:
            raise ValueError("task adoption allowlist may contain only the approved exact task names")
        if backup_directory is None:
            raise ValueError("task adoption requires an ignored backup directory under repository tmp/")

    schedules = policy.get("schedules", {})
    actions = policy.get("scheduled_task_actions", {})
    if policy_ids is not None:
        unknown_policy_ids = policy_ids - actions.keys()
        if unknown_policy_ids:
            raise ValueError(f"No scheduled task actions configured for: {sorted(unknown_policy_ids)}")
    if adoption_names:
        if policy_ids is None:
            raise ValueError("task adoption requires policy selection limited to only allowlisted task names")
        selected_task_names: set[str] = set()
        for policy_id in policy_ids:
            schedule = schedules.get(policy_id)
            if not isinstance(schedule, dict):
                raise ValueError(f"No schedule configured for task policy {policy_id}")
            selected_task_names.add(f"{schedule['task_name']}{task_name_suffix}")
        if not selected_task_names or selected_task_names - adoption_names:
            raise ValueError("task adoption policy selection may contain only allowlisted task names")
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
            working_directory_root=working_directory_root,
            task_name_suffix=task_name_suffix,
        )
        definitions.append((task_name, xml_text))

    if apply and adoption_names:
        adoption_names, validated_backup_directory = _validate_adoption_options(
            adoption_names,
            backup_directory,
            repository_root,
        )
        if validated_backup_directory is None:
            raise ValueError("task adoption requires an ignored backup directory under repository tmp/")
        task_paths = _scheduled_task_paths()
        prepared_backups: dict[str, Path] = {}
        for task_name, _ in definitions:
            target_path = "\\" + task_name.lstrip("\\")
            if target_path in task_paths:
                existing_xml, _ = _export_scheduled_task(task_name)
                prepared_backups[task_name] = _save_task_backup(
                    task_name,
                    existing_xml,
                    validated_backup_directory,
                )
        for task_name, xml_text in definitions:
            register_task(
                task_name,
                xml_text,
                adopt_existing_task_names=set(adoption_names),
                backup_directory=backup_directory,
                repository_root=repository_root,
                _prepared_backup_file=prepared_backups.get(task_name),
            )
    elif apply:
        for task_name, xml_text in definitions:
            register_task(task_name, xml_text)
    return definitions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-file", type=Path, default=_POLICY_FILE)
    parser.add_argument("--apply", action="store_true", help="Register tasks (default: print dry-run XML).")
    parser.add_argument("--task-name-suffix", default="", help="Append a local-only suffix to task names.")
    parser.add_argument("--policy-id", action="append", help="Synchronize only this policy id; may be repeated.")
    parser.add_argument(
        "--adopt-existing-task",
        action="append",
        choices=sorted(_ADOPTABLE_TASK_NAMES),
        help="Explicitly allow adoption of this approved existing task name.",
    )
    parser.add_argument(
        "--backup-directory",
        type=Path,
        help="Existing Git-ignored backup directory beneath the repository tmp/.",
    )
    parser.add_argument(
        "--working-directory-root",
        type=Path,
        help="Root for relative task action working directories (default: policy repository root).",
    )
    args = parser.parse_args(argv)
    if bool(args.adopt_existing_task) != bool(args.backup_directory):
        parser.error("--adopt-existing-task and --backup-directory must be provided together")

    policy = json.loads(args.policy_file.read_text(encoding="utf-8"))
    definitions = sync_policy_tasks(
        policy,
        args.policy_file.resolve().parents[2],
        now_utc=datetime.now(timezone.utc),
        apply=args.apply,
        task_name_suffix=args.task_name_suffix,
        policy_ids=set(args.policy_id) if args.policy_id else None,
        adopt_existing_task_names=set(args.adopt_existing_task) if args.adopt_existing_task else None,
        backup_directory=args.backup_directory,
        working_directory_root=args.working_directory_root,
    )
    mode = "Registered" if args.apply else "Dry run"
    for task_name, xml_text in definitions:
        print(f"{mode}: {task_name}")
        if not args.apply:
            print(xml_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())