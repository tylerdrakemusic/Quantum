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
    monkeypatch.setattr(sync_scheduled_tasks, "_is_windows", lambda: True)
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


def test_export_scheduled_task_ignores_mismatched_xml_encoding_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xml_bytes = (
        b'<?xml version="1.0" encoding="UTF-16"?>'
        b'<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
        b"<RegistrationInfo><Description>Caf\xc3\xa9</Description></RegistrationInfo></Task>"
    )

    def run(command: list[str], **_kwargs) -> sync_scheduled_tasks.subprocess.CompletedProcess:
        assert command == ["schtasks.exe", "/Query", "/TN", "ExistingTask", "/XML"]
        return sync_scheduled_tasks.subprocess.CompletedProcess(
            command, 0, stdout=xml_bytes, stderr=b""
        )

    monkeypatch.setattr(sync_scheduled_tasks.subprocess, "run", run)

    exported_bytes, root = sync_scheduled_tasks._export_scheduled_task("ExistingTask")

    assert exported_bytes == xml_bytes
    assert root.findtext(sync_scheduled_tasks._tag("RegistrationInfo") + "/" +
                         sync_scheduled_tasks._tag("Description")) == "Caf\u00e9"


def test_register_task_refuses_to_replace_an_unmanaged_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sync_scheduled_tasks, "_is_windows", lambda: True)
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


@pytest.mark.parametrize("task_name", ["QuantumCacheFill_Monthly", "ShorsMonthlyBench"])
def test_register_task_adopts_allowlisted_task_after_backing_up_existing_xml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    task_name: str,
) -> None:
    monkeypatch.setattr(sync_scheduled_tasks, "_is_windows", lambda: True)
    backup_directory = tmp_path / "tmp" / "local" / "scheduled-task-backups"
    backup_directory.mkdir(parents=True)
    existing_backup = backup_directory / "existing.xml"
    existing_backup.write_bytes(b"preserve this earlier backup")
    repository_root = tmp_path
    existing_xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
        b"<RegistrationInfo><Description>Existing operator task</Description>"
        b"</RegistrationInfo></Task>"
    )
    calls: list[list[str]] = []
    backup_bytes_at_create: list[bytes] = []

    def run(command: list[str], **_kwargs) -> sync_scheduled_tasks.subprocess.CompletedProcess:
        calls.append(command)
        if command[0] == "git":
            return sync_scheduled_tasks.subprocess.CompletedProcess(command, 0)
        if command[1:3] == ["/Query", "/FO"]:
            return sync_scheduled_tasks.subprocess.CompletedProcess(
                command,
                0,
                stdout=f'"\\{task_name}","Ready"\r\n',
                stderr="",
            )
        if command[1:3] == ["/Query", "/TN"]:
            return sync_scheduled_tasks.subprocess.CompletedProcess(
                command, 0, stdout=existing_xml, stderr=b""
            )
        if command[1] == "/Create":
            backup_files = [
                path for path in backup_directory.glob("*.xml") if path != existing_backup
            ]
            backup_bytes_at_create.extend(path.read_bytes() for path in backup_files)
            return sync_scheduled_tasks.subprocess.CompletedProcess(command, 0)
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(sync_scheduled_tasks.subprocess, "run", run)

    register_task(
        task_name,
        "<Task />",
        adopt_existing_task_names={task_name},
        backup_directory=backup_directory,
        repository_root=repository_root,
    )

    assert len(backup_bytes_at_create) == 1
    assert backup_bytes_at_create[0] == existing_xml
    assert existing_backup.read_bytes() == b"preserve this earlier backup"
    assert calls.index(next(command for command in calls if command[1] == "/Create")) > calls.index(
        next(command for command in calls if command[1:3] == ["/Query", "/TN"])
    )


def test_register_task_accepts_prepared_utf8_backup_with_utf16_declaration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sync_scheduled_tasks, "_is_windows", lambda: True)
    task_name = "ShorsMonthlyBench"
    backup_directory = tmp_path / "tmp" / "local" / "scheduled-task-backups"
    backup_directory.mkdir(parents=True)
    _, xml_text = build_task_definition(
        task_name=task_name,
        schedule={"day_of_month": 1, "hour": 8, "minute": 0},
        action={
            "executable": r"C:\G\python.exe",
            "arguments": [r"tools\run_shors_bench.py", "--scheduled"],
            "working_directory": ".",
            "execution_time_limit_seconds": 900,
        },
        repository_root=tmp_path,
        now_utc=datetime(2026, 11, 2, 7, tzinfo=timezone.utc),
    )
    backup_bytes = xml_text.replace("encoding='utf-8'", 'encoding="UTF-16"', 1).encode("utf-8")
    backup_path = backup_directory / f"{task_name}_preexisting.xml"
    backup_path.write_bytes(backup_bytes)
    calls: list[list[str]] = []
    backup_bytes_at_create: list[bytes] = []

    def run(command: list[str], **_kwargs) -> sync_scheduled_tasks.subprocess.CompletedProcess:
        calls.append(command)
        if command[0] == "git":
            return sync_scheduled_tasks.subprocess.CompletedProcess(command, 0)
        if command[1:3] == ["/Query", "/FO"]:
            return sync_scheduled_tasks.subprocess.CompletedProcess(
                command,
                0,
                stdout=f'"\\{task_name}","Ready"\r\n',
                stderr="",
            )
        if command[1:3] == ["/Query", "/TN"]:
            return sync_scheduled_tasks.subprocess.CompletedProcess(
                command, 0, stdout=backup_bytes, stderr=b""
            )
        if command[1] == "/Create":
            backup_bytes_at_create.append(backup_path.read_bytes())
            return sync_scheduled_tasks.subprocess.CompletedProcess(command, 0)
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(sync_scheduled_tasks.subprocess, "run", run)

    register_task(
        task_name,
        xml_text,
        adopt_existing_task_names={task_name},
        backup_directory=backup_directory,
        repository_root=tmp_path,
        _prepared_backup_file=backup_path,
    )

    assert [command[1] for command in calls if command[0] == "schtasks.exe"] == [
        "/Query",
        "/Query",
        "/Create",
    ]
    assert backup_bytes_at_create == [backup_bytes]
    assert backup_path.read_bytes() == backup_bytes


def test_register_task_rejects_prepared_backup_that_differs_from_live_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sync_scheduled_tasks, "_is_windows", lambda: True)
    task_name = "ShorsMonthlyBench"
    backup_directory = tmp_path / "tmp" / "local" / "scheduled-task-backups"
    backup_directory.mkdir(parents=True)
    backup_path = backup_directory / f"{task_name}_preexisting.xml"
    backup_bytes = (
        b'<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
        b"<RegistrationInfo><Description>Stale task</Description></RegistrationInfo></Task>"
    )
    live_task_bytes = (
        b'<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
        b"<RegistrationInfo><Description>Current task</Description></RegistrationInfo></Task>"
    )
    backup_path.write_bytes(backup_bytes)
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs) -> sync_scheduled_tasks.subprocess.CompletedProcess:
        calls.append(command)
        if command[0] == "git":
            return sync_scheduled_tasks.subprocess.CompletedProcess(command, 0)
        if command[1:3] == ["/Query", "/FO"]:
            return sync_scheduled_tasks.subprocess.CompletedProcess(
                command,
                0,
                stdout=f'"\\{task_name}","Ready"\r\n',
                stderr="",
            )
        if command[1:3] == ["/Query", "/TN"]:
            return sync_scheduled_tasks.subprocess.CompletedProcess(
                command, 0, stdout=live_task_bytes, stderr=b""
            )
        if command[1] == "/Create":
            return sync_scheduled_tasks.subprocess.CompletedProcess(command, 0)
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(sync_scheduled_tasks.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="backup"):
        register_task(
            task_name,
            "<Task />",
            adopt_existing_task_names={task_name},
            backup_directory=backup_directory,
            repository_root=tmp_path,
            _prepared_backup_file=backup_path,
        )

    assert not any(command[1] == "/Create" for command in calls)
    assert any(command[1:3] == ["/Query", "/TN"] for command in calls)
    assert backup_path.read_bytes() == backup_bytes


def test_register_task_rejects_names_outside_the_adoption_allowlist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sync_scheduled_tasks, "_is_windows", lambda: True)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        sync_scheduled_tasks.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command),
    )
    backup_directory = tmp_path / "tmp" / "local" / "scheduled-task-backups"
    backup_directory.mkdir(parents=True)

    with pytest.raises(ValueError, match="allowlist"):
        register_task(
            "OperatorOwnedTask",
            "<Task />",
            adopt_existing_task_names={"OperatorOwnedTask"},
            backup_directory=backup_directory,
            repository_root=tmp_path,
        )

    assert calls == []


@pytest.mark.parametrize(
    ("backup_relative_path", "git_returncode", "error_match"),
    [
        ("backups", 0, "under.*tmp"),
        ("tmp/local/scheduled-task-backups", 1, "ignored"),
    ],
)
def test_register_task_requires_an_ignored_backup_directory_under_tmp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    backup_relative_path: str,
    git_returncode: int,
    error_match: str,
) -> None:
    monkeypatch.setattr(sync_scheduled_tasks, "_is_windows", lambda: True)
    backup_directory = tmp_path / backup_relative_path
    backup_directory.mkdir(parents=True)
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs) -> sync_scheduled_tasks.subprocess.CompletedProcess:
        calls.append(command)
        return sync_scheduled_tasks.subprocess.CompletedProcess(command, git_returncode)

    monkeypatch.setattr(sync_scheduled_tasks.subprocess, "run", run)

    with pytest.raises(ValueError, match=error_match):
        register_task(
            "ShorsMonthlyBench",
            "<Task />",
            adopt_existing_task_names={"ShorsMonthlyBench"},
            backup_directory=backup_directory,
            repository_root=tmp_path,
        )

    assert not any(command[0] == "schtasks.exe" for command in calls)


@pytest.mark.parametrize("failure_point", ["export", "backup"])
def test_register_task_refuses_adoption_when_export_or_backup_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_point: str,
) -> None:
    monkeypatch.setattr(sync_scheduled_tasks, "_is_windows", lambda: True)
    backup_directory = tmp_path / "tmp" / "local" / "scheduled-task-backups"
    backup_directory.mkdir(parents=True)
    task_name = "ShorsMonthlyBench"
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs) -> sync_scheduled_tasks.subprocess.CompletedProcess:
        calls.append(command)
        if command[0] == "git":
            return sync_scheduled_tasks.subprocess.CompletedProcess(command, 0)
        if command[1:3] == ["/Query", "/FO"]:
            return sync_scheduled_tasks.subprocess.CompletedProcess(
                command, 0, stdout='"\\ShorsMonthlyBench","Ready"\r\n', stderr=""
            )
        if command[1:3] == ["/Query", "/TN"]:
            if failure_point == "export":
                raise sync_scheduled_tasks.subprocess.CalledProcessError(1, command)
            return sync_scheduled_tasks.subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    b'<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
                    b"<RegistrationInfo><Description>Legacy task</Description>"
                    b"</RegistrationInfo></Task>"
                ),
                stderr=b"",
            )
        if command[1] == "/Create":
            return sync_scheduled_tasks.subprocess.CompletedProcess(command, 0)
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(sync_scheduled_tasks.subprocess, "run", run)
    if failure_point == "backup":
        monkeypatch.setattr(
            sync_scheduled_tasks.tempfile,
            "NamedTemporaryFile",
            lambda **_kwargs: (_ for _ in ()).throw(PermissionError("backup denied")),
        )

    with pytest.raises(RuntimeError):
        register_task(
            task_name,
            "<Task />",
            adopt_existing_task_names={task_name},
            backup_directory=backup_directory,
            repository_root=tmp_path,
        )

    assert not any(command[1] == "/Create" for command in calls)


def test_policy_sync_exports_all_adopted_tasks_before_registering_any(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sync_scheduled_tasks, "_is_windows", lambda: True)
    policy_path = PROJECT_ROOT / "src" / "config" / "execution_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    backup_directory = tmp_path / "tmp" / "local" / "scheduled-task-backups"
    backup_directory.mkdir(parents=True)
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs) -> sync_scheduled_tasks.subprocess.CompletedProcess:
        calls.append(command)
        if command[0] == "git":
            return sync_scheduled_tasks.subprocess.CompletedProcess(command, 0)
        if command[1:3] == ["/Query", "/FO"]:
            return sync_scheduled_tasks.subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    '"\\QuantumCacheFill_Monthly","Ready"\r\n'
                    '"\\ShorsMonthlyBench","Ready"\r\n'
                ),
                stderr="",
            )
        if command[1:3] == ["/Query", "/TN"]:
            if command[3] == "ShorsMonthlyBench":
                raise sync_scheduled_tasks.subprocess.CalledProcessError(1, command)
            return sync_scheduled_tasks.subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    b'<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
                    b"<RegistrationInfo><Description>Legacy task</Description>"
                    b"</RegistrationInfo></Task>"
                ),
                stderr=b"",
            )
        if command[1] == "/Create":
            return sync_scheduled_tasks.subprocess.CompletedProcess(command, 0)
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(sync_scheduled_tasks.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="export and verify"):
        sync_policy_tasks(
            policy,
            tmp_path,
            now_utc=datetime(2026, 10, 19, 7, 30, tzinfo=timezone.utc),
            apply=True,
            policy_ids={"quantum_cache_fill_monthly", "shors_monthly_benchmark"},
            adopt_existing_task_names={"QuantumCacheFill_Monthly", "ShorsMonthlyBench"},
            backup_directory=backup_directory,
        )

    assert not any(command[1] == "/Create" for command in calls)
    assert len(list(backup_directory.glob("*.xml"))) == 1


def test_register_task_refuses_to_replace_managed_task_with_unverified_action(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sync_scheduled_tasks, "_is_windows", lambda: True)
    calls: list[list[str]] = []
    task_name, expected_xml = build_task_definition(
        task_name="ExistingTask",
        schedule={"schedule": "daily", "time_utc": "07:00"},
        action={
            "executable": r"C:\G\python.exe",
            "arguments": [r"tools\fill_cache.py"],
            "working_directory": ".",
            "execution_time_limit_seconds": 600,
        },
        repository_root=tmp_path,
        now_utc=datetime(2026, 11, 2, 6, tzinfo=timezone.utc),
    )

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
                    "<RegistrationInfo><Description>Managed by Quantum execution_policy.json.</Description>"
                    "</RegistrationInfo><Actions Context=\"Author\"><Exec>"
                    "<Command>C:\\Other\\python.exe</Command><Arguments>unverified.py</Arguments>"
                    "<WorkingDirectory>C:\\Other</WorkingDirectory></Exec></Actions></Task>"
                ),
                stderr="",
            )
        if command[1] == "/Create":
            return sync_scheduled_tasks.subprocess.CompletedProcess(command, 0)
        raise AssertionError(f"Unexpected schtasks command: {command}")

    monkeypatch.setattr(sync_scheduled_tasks.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="action"):
        register_task(task_name, expected_xml)

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


def test_policy_sync_forwards_explicit_adoption_allowlist_and_backup_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    policy_path = PROJECT_ROOT / "src" / "config" / "execution_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    backup_directory = tmp_path / "tmp" / "local" / "scheduled-task-backups"
    backup_directory.mkdir(parents=True)
    registered: list[tuple[str, dict[str, object]]] = []

    def record_registration(task_name: str, _xml_text: str, **kwargs: object) -> None:
        registered.append((task_name, kwargs))

    monkeypatch.setattr(sync_scheduled_tasks, "register_task", record_registration)
    monkeypatch.setattr(
        sync_scheduled_tasks,
        "_validate_adoption_options",
        lambda names, backup, _root: (frozenset(names or ()), backup),
    )
    monkeypatch.setattr(sync_scheduled_tasks, "_scheduled_task_paths", lambda: set())

    definitions = sync_policy_tasks(
        policy,
        PROJECT_ROOT,
        now_utc=datetime(2026, 10, 19, 7, 30, tzinfo=timezone.utc),
        apply=True,
        policy_ids={"quantum_cache_fill_monthly", "shors_monthly_benchmark"},
        adopt_existing_task_names={"QuantumCacheFill_Monthly", "ShorsMonthlyBench"},
        backup_directory=backup_directory,
    )

    assert [name for name, _ in definitions] == ["QuantumCacheFill_Monthly", "ShorsMonthlyBench"]
    assert [name for name, _ in registered] == ["QuantumCacheFill_Monthly", "ShorsMonthlyBench"]
    assert all(
        kwargs["adopt_existing_task_names"] == {"QuantumCacheFill_Monthly", "ShorsMonthlyBench"}
        and kwargs["backup_directory"] == backup_directory
        and kwargs["repository_root"] == PROJECT_ROOT
        for _, kwargs in registered
    )


@pytest.mark.parametrize(
    "policy_ids",
    [None, {"quantum_cache_fill_monthly", "vqe_monthly_benchmark"}],
)
def test_policy_sync_rejects_adoption_that_could_register_unrelated_tasks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    policy_ids: set[str] | None,
) -> None:
    policy_path = PROJECT_ROOT / "src" / "config" / "execution_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    backup_directory = tmp_path / "tmp" / "local" / "scheduled-task-backups"
    backup_directory.mkdir(parents=True)
    registered: list[str] = []
    monkeypatch.setattr(
        sync_scheduled_tasks,
        "register_task",
        lambda task_name, *_args, **_kwargs: registered.append(task_name),
    )

    with pytest.raises(ValueError, match="only allowlisted task names"):
        sync_policy_tasks(
            policy,
            PROJECT_ROOT,
            now_utc=datetime(2026, 10, 19, 7, 30, tzinfo=timezone.utc),
            apply=True,
            policy_ids=policy_ids,
            adopt_existing_task_names={"QuantumCacheFill_Monthly", "ShorsMonthlyBench"},
            backup_directory=backup_directory,
        )

    assert registered == []


def test_cli_accepts_explicit_adoption_options_without_applying(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    policy_file = tmp_path / "execution_policy.json"
    policy_file.write_text('{"timezone": "UTC"}', encoding="utf-8")
    backup_directory = tmp_path / "tmp" / "local" / "scheduled-task-backups"
    backup_directory.mkdir(parents=True)
    runtime_root = tmp_path / "main-runtime"
    runtime_root.mkdir()
    received: dict[str, object] = {}

    def capture_sync(_policy: dict[str, object], _root: Path, **kwargs: object) -> list[tuple[str, str]]:
        received.update(kwargs)
        return []

    monkeypatch.setattr(sync_scheduled_tasks, "sync_policy_tasks", capture_sync)

    result = sync_scheduled_tasks.main(
        [
            "--policy-file",
            str(policy_file),
            "--adopt-existing-task",
            "QuantumCacheFill_Monthly",
            "--policy-id",
            "quantum_cache_fill_monthly",
            "--backup-directory",
            str(backup_directory),
            "--working-directory-root",
            str(runtime_root),
        ]
    )

    assert result == 0
    assert received["adopt_existing_task_names"] == {"QuantumCacheFill_Monthly"}
    assert received["backup_directory"] == backup_directory
    assert received["working_directory_root"] == runtime_root
    assert received["apply"] is False


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


def test_policy_sync_separates_backup_and_working_directory_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "worktree"
    policy_file = repository_root / "src" / "config" / "execution_policy.json"
    policy_file.parent.mkdir(parents=True)
    source_policy = PROJECT_ROOT / "src" / "config" / "execution_policy.json"
    policy_file.write_text(source_policy.read_text(encoding="utf-8"), encoding="utf-8")
    policy = json.loads(policy_file.read_text(encoding="utf-8"))
    backup_directory = repository_root / "tmp" / "local" / "scheduled-task-backups"
    backup_directory.mkdir(parents=True)
    runtime_root = tmp_path / "main-runtime"
    runtime_root.mkdir()
    ignore_check_roots: list[Path] = []
    registered: list[tuple[str, dict[str, object]]] = []

    def check_backup_is_ignored(
        command: list[str],
        **kwargs: object,
    ) -> sync_scheduled_tasks.subprocess.CompletedProcess:
        ignore_check_roots.append(Path(str(kwargs["cwd"])).resolve())
        return sync_scheduled_tasks.subprocess.CompletedProcess(command, 0)

    def capture_registration(
        task_name: str,
        _xml_text: str,
        **kwargs: object,
    ) -> None:
        registered.append((task_name, kwargs))

    monkeypatch.setattr(sync_scheduled_tasks.subprocess, "run", check_backup_is_ignored)
    monkeypatch.setattr(sync_scheduled_tasks, "_scheduled_task_paths", lambda: set())
    monkeypatch.setattr(sync_scheduled_tasks, "register_task", capture_registration)

    definitions = sync_policy_tasks(
        policy,
        repository_root,
        working_directory_root=runtime_root,
        now_utc=datetime(2026, 10, 19, 7, 30, tzinfo=timezone.utc),
        apply=True,
        policy_ids={"quantum_cache_fill_monthly", "shors_monthly_benchmark"},
        adopt_existing_task_names={"QuantumCacheFill_Monthly", "ShorsMonthlyBench"},
        backup_directory=backup_directory,
    )

    assert [name for name, _ in definitions] == [
        "QuantumCacheFill_Monthly",
        "ShorsMonthlyBench",
    ]
    namespace = {"task": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert all(
        ET.fromstring(xml_text).findtext(
            "task:Actions/task:Exec/task:WorkingDirectory",
            namespaces=namespace,
        )
        == str(runtime_root.resolve())
        for _, xml_text in definitions
    )
    assert ignore_check_roots == [repository_root.resolve()]
    assert [name for name, _ in registered] == [
        "QuantumCacheFill_Monthly",
        "ShorsMonthlyBench",
    ]
    assert all(
        kwargs["repository_root"] == repository_root
        and kwargs["backup_directory"] == backup_directory
        for _, kwargs in registered
    )
