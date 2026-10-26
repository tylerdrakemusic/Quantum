from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import run_ruff_advisory


def test_runner_records_findings_as_advisory_without_modifying_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "pyproject.toml"
    config_path.write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
    source_path = tmp_path / "sample.py"
    source_path.write_text("import os\n", encoding="utf-8")
    original_source = source_path.read_bytes()
    output_dir = tmp_path / "tmp" / "ruff-advisory"
    commands: list[list[str]] = []

    def fake_run_command(command: list[str]) -> dict[str, str | int | None]:
        commands.append(command)
        if command[-1:] == ["--version"]:
            return {"returncode": 0, "stdout": "ruff 0.17.2\n", "stderr": ""}
        if command == ["git", "rev-parse", "HEAD"]:
            return {"returncode": 0, "stdout": "abc123\n", "stderr": ""}
        if command == ["git", "remote", "get-url", "origin"]:
            return {
                "returncode": 0,
                "stdout": "https://github.com/tylerdrakemusic/Quantum.git\n",
                "stderr": "",
            }
        if "check" in command:
            return {
                "returncode": 1,
                "stdout": '[{"code":"F401","filename":"sample.py"}]',
                "stderr": "",
            }
        if "format" in command:
            return {
                "returncode": 1,
                "stdout": "--- sample.py\n+++ sample.py\n",
                "stderr": "1 file would be reformatted, 0 files already formatted\n",
            }
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_ruff_advisory, "run_command", fake_run_command)

    result = run_ruff_advisory.main(
        [
            "--config",
            "pyproject.toml",
            "--output-dir",
            str(output_dir),
            "--paths",
            "sample.py",
        ]
    )

    report = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert result == 0
    assert report["repository"] == "tylerdrakemusic/Quantum"
    assert report["commit"] == "abc123"
    assert report["ruff_version"] == "ruff 0.17.2"
    assert report["scan_scope"] == "Explicit Python paths: sample.py"
    assert commands[1][-1] == "sample.py"
    assert commands[2][-1] == "sample.py"
    assert report["finding_counts"]["check_total"] == 1
    assert report["finding_counts"]["check_by_code"] == {"F401": 1}
    assert report["finding_counts"]["format_files"] == 1
    assert report["command_exit_codes"] == {"version": 0, "check": 1, "format": 1}
    assert report["tool_errors"] == {
        "version": None,
        "check": None,
        "format": None,
        "config": None,
        "commit": None,
        "repository": None,
    }
    assert source_path.read_bytes() == original_source


def test_runner_keeps_raw_diagnostics_local_and_sanitizes_ci_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "pyproject.toml"
    config_path.write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
    source_path = tmp_path / "private" / "SENTINEL_PATH.py"
    source_path.parent.mkdir()
    source_secret = "SOURCE_SECRET_SENTINEL_7e31"
    source_path.write_text(f"TOKEN = '{source_secret}'\n", encoding="utf-8")
    source_arg = source_path.relative_to(tmp_path).as_posix()
    remote_url = "https://token:REMOTE_SECRET_SENTINEL@github.com/private/repo.git"
    tool_error = "TOOL_STDERR_SECRET_SENTINEL"
    local_dir = tmp_path / "tmp" / "ruff-advisory-local"
    ci_dir = tmp_path / "tmp" / "ruff-advisory-ci" / "4242-1"
    step_summary_path = tmp_path / "github-step-summary.md"
    sentinel_values = [source_arg, source_secret, remote_url, tool_error]

    def fake_run_command(command: list[str]) -> dict[str, str | int | None]:
        if command[-1:] == ["--version"]:
            return {"returncode": 0, "stdout": "ruff 0.17.2\n", "stderr": tool_error}
        if command == ["git", "rev-parse", "HEAD"]:
            return {"returncode": 0, "stdout": "abc123\n", "stderr": ""}
        if command == ["git", "remote", "get-url", "origin"]:
            return {"returncode": 0, "stdout": f"{remote_url}\n", "stderr": ""}
        if "check" in command:
            return {
                "returncode": 1,
                "stdout": json.dumps(
                    [
                        {
                            "code": "F821",
                            "filename": source_arg,
                            "message": source_secret,
                            "cell": source_secret,
                        }
                    ]
                ),
                "stderr": "",
            }
        if "format" in command:
            return {
                "returncode": 1,
                "stdout": (
                    f"--- {source_arg}\n+++ {source_arg}\n"
                    f"-TOKEN = '{source_secret}'\n+TOKEN = {source_secret!r}\n"
                    "1 file would be reformatted\n"
                ),
                "stderr": "",
            }
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "tylerdrakemusic/Quantum")
    monkeypatch.setenv("GITHUB_RUN_ID", "4242")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step_summary_path))
    monkeypatch.setattr(run_ruff_advisory, "run_command", fake_run_command)

    result = run_ruff_advisory.main(
        ["--config", "pyproject.toml", "--output-dir", str(local_dir), "--paths", source_arg]
    )

    local_text = "\n".join(
        path.read_text(encoding="utf-8") for path in local_dir.iterdir() if path.is_file()
    )
    assert result == 0
    for sentinel in sentinel_values:
        assert sentinel in local_text

    assert sorted(path.name for path in ci_dir.iterdir()) == ["summary.json"]
    ci_report = json.loads((ci_dir / "summary.json").read_text(encoding="utf-8"))
    assert set(ci_report) == {
        "repository",
        "commit",
        "ruff_version",
        "config_sha256",
        "scan_scope",
        "elapsed_seconds",
        "finding_counts",
        "command_exit_codes",
        "tool_errors",
    }
    assert ci_report["tool_errors"]["version"] is True
    ci_text = (ci_dir / "summary.json").read_text(encoding="utf-8")
    step_summary = step_summary_path.read_text(encoding="utf-8")
    captured = capsys.readouterr()
    captured_logs = captured.out + captured.err
    for sentinel in sentinel_values:
        assert sentinel not in ci_text
        assert sentinel not in step_summary
        assert sentinel not in captured_logs


def test_runner_marks_successful_unpinned_ruff_version_as_ci_tool_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "pyproject.toml"
    config_path.write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
    ci_dir = tmp_path / "tmp" / "ruff-advisory-ci" / "4343-1"
    step_summary_path = tmp_path / "step-summary.md"

    def fake_run_command(command: list[str]) -> dict[str, str | int | None]:
        if command[-1:] == ["--version"]:
            return {"returncode": 0, "stdout": "ruff 0.17.3\n", "stderr": ""}
        if command == ["git", "rev-parse", "HEAD"]:
            return {"returncode": 0, "stdout": "abc123\n", "stderr": ""}
        if command == ["git", "remote", "get-url", "origin"]:
            return {
                "returncode": 0,
                "stdout": "https://github.com/tylerdrakemusic/Quantum.git\n",
                "stderr": "",
            }
        if "check" in command:
            return {"returncode": 0, "stdout": "[]", "stderr": ""}
        if "format" in command:
            return {"returncode": 0, "stdout": "", "stderr": ""}
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "tylerdrakemusic/Quantum")
    monkeypatch.setenv("GITHUB_RUN_ID", "4343")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step_summary_path))
    monkeypatch.setattr(run_ruff_advisory, "run_command", fake_run_command)

    result = run_ruff_advisory.main(
        ["--config", "pyproject.toml", "--output-dir", str(tmp_path / "local"), "--paths", "sample.py"]
    )

    ci_report = json.loads((ci_dir / "summary.json").read_text(encoding="utf-8"))
    assert result == 0
    assert ci_report["command_exit_codes"]["version"] == 0
    assert ci_report["tool_errors"]["version"] is True
    assert ci_report["ruff_version"] == "unavailable"
