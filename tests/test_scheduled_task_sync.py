from __future__ import annotations

import xml.etree.ElementTree as ET
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import sync_scheduled_tasks
from sync_scheduled_tasks import build_task_definition, register_task, sync_policy_tasks


def test_monthly_task_definition_uses_policy_utc_and_scheduled_shor_approval(
    tmp_path: Path,
) -> None:
    task_name, xml_text = build_task_definition(
        task_name="ShorsMonthlyBench",
        schedule={"day_of_month": 1, "hour": 8, "minute": 0},
        action={
            "executable": r"C:\G\python.exe",
            "arguments": [r"tools\run_shors_bench.py", "--scheduled"],
            "working_directory": ".",
            "execution_time_limit_seconds": 900,
            "start_when_available": False,
        },
        repository_root=tmp_path,
        now_utc=datetime(2026, 10, 19, 12, tzinfo=timezone.utc),
        task_name_suffix="-FR-check",
    )

    namespace = {"task": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    root = ET.fromstring(xml_text)
    assert task_name == "ShorsMonthlyBench-FR-check"
    assert root.findtext("task:Triggers/task:CalendarTrigger/task:StartBoundary", namespaces=namespace) == (
        "2026-11-01T08:00:00Z"
    )
    assert root.findtext("task:Triggers/task:CalendarTrigger/task:ScheduleByMonth/"
                         "task:DaysOfMonth/task:Day", namespaces=namespace) == "1"
    assert root.findtext("task:Settings/task:ExecutionTimeLimit", namespaces=namespace) == "PT900S"
    assert root.findtext("task:Actions/task:Exec/task:Command", namespaces=namespace) == r"C:\G\python.exe"
    assert root.findtext("task:Actions/task:Exec/task:Arguments", namespaces=namespace) == (
        r"tools\run_shors_bench.py --scheduled"
    )
    assert root.findtext("task:Actions/task:Exec/task:WorkingDirectory", namespaces=namespace) == str(tmp_path)


def test_policy_sync_orders_backend_health_before_shor_and_defaults_to_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_path = PROJECT_ROOT / "src" / "config" / "execution_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    monkeypatch.setattr(
        "sync_scheduled_tasks.register_task",
        lambda *_args: pytest.fail("dry-run must not register a scheduled task"),
    )
    names_and_xml = sync_policy_tasks(
        policy,
        PROJECT_ROOT,
        now_utc=datetime(2026, 10, 19, 7, 30, tzinfo=timezone.utc),
        task_name_suffix="-verify",
    )
    definitions = dict(names_and_xml)
    namespace = {"task": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    monitor = ET.fromstring(definitions["QuantumBackendAvailabilityMonitor_Daily-verify"])
    shor = ET.fromstring(definitions["ShorsMonthlyBench-verify"])

    assert monitor.findtext("task:Triggers/task:CalendarTrigger/task:StartBoundary", namespaces=namespace) == (
        "2026-10-19T07:45:00Z"
    )
    assert shor.findtext("task:Triggers/task:CalendarTrigger/task:StartBoundary", namespaces=namespace) == (
        "2026-11-01T08:00:00Z"
    )
    assert set(definitions) == {
        "QuantumCacheFill_Monthly-verify",
        "ShorsMonthlyBench-verify",
        "VQEMonthlyBench-verify",
        "QuantumBackendAvailabilityMonitor_Daily-verify",
    }
def test_task_scheduler_xml_file_declaration_matches_utf16_encoding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, xml_text = build_task_definition(
        task_name="ShorsMonthlyBench",
        schedule={"day_of_month": 1, "hour": 8, "minute": 0},
        action={
            "executable": r"C:\G\python.exe",
            "arguments": [r"tools\run_shors_bench.py", "--scheduled"],
            "working_directory": ".",
            "execution_time_limit_seconds": 900,
        },
        repository_root=tmp_path,
        now_utc=datetime(2026, 10, 19, 12, tzinfo=timezone.utc),
    )
    parsed_roots: list[ET.Element] = []

    def parse_registered_file(command: list[str], **_kwargs) -> None:
        if command[1:3] == ["/Query", "/FO"]:
            return sync_scheduled_tasks.subprocess.CompletedProcess(
                command, 0, stdout="", stderr=""
            )
        assert command[1] == "/Create"
        xml_path = Path(command[5])
        payload = xml_path.read_bytes()
        assert payload.startswith(b"\xff\xfe")
        parsed_roots.append(ET.fromstring(payload))
        return sync_scheduled_tasks.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(sync_scheduled_tasks.subprocess, "run", parse_registered_file)
    register_task("ShorsMonthlyBench-test", xml_text)

    assert len(parsed_roots) == 1


def test_register_task_refuses_to_replace_an_unmanaged_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sync_scheduled_tasks.os, "name", "nt")
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs) -> sync_scheduled_tasks.subprocess.CompletedProcess:
        calls.append(command)
        if command[1:3] == ["/Query", "/FO"]:
            return sync_scheduled_tasks.subprocess.CompletedProcess(
                command,
                0,
                stdout='"\\ExistingTask","Ready"\r\n',
                stderr="",
            )
        if command[1:3] == ["/Query", "/TN"]:
            return sync_scheduled_tasks.subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    '<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
                    "<RegistrationInfo><Description>Created by another tool</Description>"
                    "</RegistrationInfo></Task>"
                ),
                stderr="",
            )
        if command[1] == "/Create":
            return sync_scheduled_tasks.subprocess.CompletedProcess(command, 0)
        raise AssertionError(f"Unexpected schtasks command: {command}")

    monkeypatch.setattr(sync_scheduled_tasks.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="not managed by Quantum"):
        register_task("ExistingTask", "<Task />")

    assert not any(command[1] == "/Create" for command in calls)


def test_policy_sync_can_select_one_policy_without_registering_others() -> None:
    policy_path = PROJECT_ROOT / "src" / "config" / "execution_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    definitions = sync_policy_tasks(
        policy,
        PROJECT_ROOT,
        now_utc=datetime(2026, 10, 20, 3, 30, tzinfo=timezone.utc),
        task_name_suffix="-verify",
        policy_ids={"shors_monthly_benchmark"},
    )

    assert [name for name, _ in definitions] == ["ShorsMonthlyBench-verify"]


def test_policy_sync_rejects_non_utc_schedule_basis() -> None:
    policy_path = PROJECT_ROOT / "src" / "config" / "execution_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["timezone"] = "America/Denver"

    with pytest.raises(ValueError, match="timezone must be UTC"):
        sync_policy_tasks(
            policy,
            PROJECT_ROOT,
            now_utc=datetime(2026, 10, 19, 12, tzinfo=timezone.utc),
        )
