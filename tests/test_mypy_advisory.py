from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
import tomllib
from typing import Sequence

import pytest


def test_initial_mypy_configuration_limits_scan_to_one_module() -> None:
    project_root = Path(__file__).resolve().parent.parent
    config = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    mypy_config = config.get("tool", {}).get("mypy", {})

    assert mypy_config.get("files") == ["src/quantum_toolkit/benchmark_provenance.py"]
    assert mypy_config.get("python_version") == "3.11"
    assert mypy_config.get("no_incremental") is True
    assert mypy_config.get("follow_imports") == "skip"


def test_mypy_artifact_upload_does_not_gate_ci() -> None:
    project_root = Path(__file__).resolve().parent.parent
    workflow = (project_root / ".github" / "workflows" / "test.yml").read_text(
        encoding="utf-8"
    )
    step_match = re.search(
        r"(?ms)^      - name: Upload advisory mypy report\n(?P<body>.*?)(?=^      - name:|\Z)",
        workflow,
    )

    assert step_match is not None
    assert re.search(r"(?m)^        continue-on-error: true$", step_match.group("body"))


def test_runner_reports_findings_and_shared_metadata_without_gating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_spec = importlib.util.find_spec("tools.run_mypy_advisory")
    assert module_spec is not None, "mypy advisory runner is missing"
    from tools import run_mypy_advisory

    config_text = "[tool.mypy]\npython_version = '3.11'\n"
    config_path = tmp_path / "pyproject.toml"
    config_path.write_text(config_text, encoding="utf-8")
    source_path = tmp_path / "src" / "quantum_toolkit" / "benchmark_provenance.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "def calculate(value: int) -> int:\n    return value\n", encoding="utf-8"
    )
    original_source = source_path.read_bytes()
    source_arg = "src/quantum_toolkit/benchmark_provenance.py"
    output_dir = tmp_path / "tmp" / "mypy-advisory"
    commands: list[list[str]] = []

    def fake_run_command(
        command: Sequence[str], *, cwd: Path | None = None
    ) -> dict[str, str | int | None]:
        commands.append(list(command))
        if command[-1:] == ["--version"]:
            return {"returncode": 0, "stdout": "mypy 1.18.2 (compiled: yes)\n", "stderr": ""}
        if list(command) == ["git", "rev-parse", "HEAD"]:
            return {"returncode": 0, "stdout": "abc1234\n", "stderr": ""}
        if list(command) == ["git", "remote", "get-url", "origin"]:
            return {
                "returncode": 0,
                "stdout": "https://github.com/tylerdrakemusic/Quantum.git\n",
                "stderr": "",
            }
        if "-m" in command and "mypy" in command:
            return {
                "returncode": 1,
                "stdout": f"{source_arg}:1: error: Incompatible return value type [return-value]\n",
                "stderr": "",
            }
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(run_mypy_advisory, "PROJECT_ROOT", tmp_path, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "tylerdrakemusic/Quantum")
    monkeypatch.setattr(run_mypy_advisory, "run_command", fake_run_command)

    result = run_mypy_advisory.main(
        [
            "--config",
            "pyproject.toml",
            "--output-dir",
            str(output_dir),
            "--paths",
            source_arg,
        ]
    )

    report = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    mypy_command = next(
        command
        for command in commands
        if "-m" in command and "mypy" in command and command[-1:] != ["--version"]
    )
    assert result == 0
    assert report["repository"] == "tylerdrakemusic/Quantum"
    assert report["commit"] == "abc1234"
    assert report["mypy_version"] == "mypy 1.18.2 (compiled: yes)"
    assert report["configuration_revision"] == hashlib.sha256(config_path.read_bytes()).hexdigest()
    assert report["scan_scope"] == f"Explicit Python paths: {source_arg}"
    assert isinstance(report["elapsed_seconds"], float)
    assert report["finding_count"] == 1
    assert "--no-incremental" in mypy_command
    assert source_arg in mypy_command
    assert source_path.read_bytes() == original_source


def test_runner_reports_mypy_version_mismatch_as_advisory_tool_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_spec = importlib.util.find_spec("tools.run_mypy_advisory")
    assert module_spec is not None, "mypy advisory runner is missing"
    from tools import run_mypy_advisory

    config_path = tmp_path / "pyproject.toml"
    config_path.write_text("[tool.mypy]\npython_version = '3.11'\n", encoding="utf-8")
    source_path = tmp_path / "src" / "quantum_toolkit" / "benchmark_provenance.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("value: int = 1\n", encoding="utf-8")
    output_dir = tmp_path / "tmp" / "mypy-advisory-local"
    ci_summary_path = tmp_path / "tmp" / "mypy-advisory-ci" / "8101-1" / "summary.json"
    step_summary_path = tmp_path / "step-summary.md"

    def fake_run_command(
        command: Sequence[str], *, cwd: Path | None = None
    ) -> dict[str, str | int | None]:
        if command[-1:] == ["--version"]:
            return {"returncode": 0, "stdout": "mypy 1.10.1 (compiled: yes)\n", "stderr": ""}
        if list(command) == ["git", "rev-parse", "HEAD"]:
            return {"returncode": 0, "stdout": "abc1234\n", "stderr": ""}
        if list(command) == ["git", "remote", "get-url", "origin"]:
            return {"returncode": 0, "stdout": "https://github.com/owner/repo.git\n", "stderr": ""}
        if "-m" in command and "mypy" in command:
            return {"returncode": 0, "stdout": "", "stderr": ""}
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(run_mypy_advisory, "PROJECT_ROOT", tmp_path, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_RUN_ID", "8101")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step_summary_path))
    monkeypatch.setattr(run_mypy_advisory, "run_command", fake_run_command)

    result = run_mypy_advisory.main(
        [
            "--config",
            "pyproject.toml",
            "--output-dir",
            str(output_dir),
            "--paths",
            "src/quantum_toolkit/benchmark_provenance.py",
        ]
    )

    report = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    ci_report = json.loads(ci_summary_path.read_text(encoding="utf-8"))
    step_summary = step_summary_path.read_text(encoding="utf-8")
    assert result == 0
    assert report["mypy_version"] == "mypy 1.10.1 (compiled: yes)"
    assert report["tool_errors"]["version"] == (
        "Expected mypy 1.18.2, observed mypy 1.10.1 (compiled: yes)"
    )
    assert report["finding_count"] == 0
    assert ci_report["mypy_version"] == "mypy 1.10.1 (compiled: yes)"
    assert ci_report["tool_errors"]["version"] is True
    assert "- Tool errors: `version`" in step_summary


def test_runner_reports_unrecognized_mypy_version_as_advisory_tool_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_spec = importlib.util.find_spec("tools.run_mypy_advisory")
    assert module_spec is not None, "mypy advisory runner is missing"
    from tools import run_mypy_advisory

    config_path = tmp_path / "pyproject.toml"
    config_path.write_text("[tool.mypy]\npython_version = '3.11'\n", encoding="utf-8")
    source_path = tmp_path / "src" / "quantum_toolkit" / "benchmark_provenance.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("value: int = 1\n", encoding="utf-8")
    output_dir = tmp_path / "tmp" / "mypy-advisory-local"
    ci_summary_path = tmp_path / "tmp" / "mypy-advisory-ci" / "8102-1" / "summary.json"

    def fake_run_command(
        command: Sequence[str], *, cwd: Path | None = None
    ) -> dict[str, str | int | None]:
        if command[-1:] == ["--version"]:
            return {"returncode": 0, "stdout": "unexpected version output\n", "stderr": ""}
        if list(command) == ["git", "rev-parse", "HEAD"]:
            return {"returncode": 0, "stdout": "abc1234\n", "stderr": ""}
        if list(command) == ["git", "remote", "get-url", "origin"]:
            return {"returncode": 0, "stdout": "https://github.com/owner/repo.git\n", "stderr": ""}
        if "-m" in command and "mypy" in command:
            return {"returncode": 0, "stdout": "", "stderr": ""}
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(run_mypy_advisory, "PROJECT_ROOT", tmp_path, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "8102")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(run_mypy_advisory, "run_command", fake_run_command)

    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    result = run_mypy_advisory.main(
        [
            "--config",
            "pyproject.toml",
            "--output-dir",
            str(output_dir),
            "--paths",
            "src/quantum_toolkit/benchmark_provenance.py",
        ]
    )

    report = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    ci_report = json.loads(ci_summary_path.read_text(encoding="utf-8"))
    assert result == 0
    assert report["mypy_version"] == "unavailable"
    assert report["tool_errors"]["version"]
    assert ci_report["mypy_version"] == "unavailable"
    assert ci_report["tool_errors"]["version"] is True


def test_runner_anchors_scope_to_repository_and_rejects_without_gating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_spec = importlib.util.find_spec("tools.run_mypy_advisory")
    assert module_spec is not None, "mypy advisory runner is missing"
    from tools import run_mypy_advisory

    repository_root = tmp_path / "repository"
    caller_root = tmp_path / "caller"
    repository_root.mkdir()
    caller_source = caller_root / "src" / "outside.py"
    caller_source.parent.mkdir(parents=True)
    caller_source.write_text("value: int = 1\n", encoding="utf-8")
    (repository_root / "pyproject.toml").write_text(
        "[tool.mypy]\npython_version = '3.11'\n", encoding="utf-8"
    )
    output_dir = tmp_path / "reports"
    commands: list[list[str]] = []

    def fake_run_command(
        command: Sequence[str], *, cwd: Path | None = None
    ) -> dict[str, str | int | None]:
        commands.append(list(command))
        if command[-1:] == ["--version"]:
            return {"returncode": 0, "stdout": "mypy 1.18.2 (compiled: yes)\n", "stderr": ""}
        if list(command) == ["git", "rev-parse", "HEAD"]:
            return {"returncode": 0, "stdout": "abc1234\n", "stderr": ""}
        if list(command) == ["git", "remote", "get-url", "origin"]:
            return {"returncode": 0, "stdout": "https://github.com/owner/repo.git\n", "stderr": ""}
        if "-m" in command and "mypy" in command:
            return {"returncode": 0, "stdout": "", "stderr": ""}
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(run_mypy_advisory, "PROJECT_ROOT", repository_root, raising=False)
    monkeypatch.chdir(caller_root)
    monkeypatch.setattr(run_mypy_advisory, "run_command", fake_run_command)

    result = run_mypy_advisory.main(
        [
            "--config",
            "pyproject.toml",
            "--output-dir",
            str(output_dir),
            "--paths",
            str(caller_source),
        ]
    )

    report = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert result == 0
    assert report["finding_count"] is None
    assert report["tool_errors"]["scope"]
    assert not any("-m" in command and "mypy" in command for command in commands)


def test_step_summary_escapes_untrusted_scope_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_spec = importlib.util.find_spec("tools.run_mypy_advisory")
    assert module_spec is not None, "mypy advisory runner is missing"
    from tools import run_mypy_advisory

    summary_path = tmp_path / "step-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    run_mypy_advisory._append_step_summary(
        {
            "repository": "owner/repo",
            "commit": "abc1234",
            "mypy_version": "mypy 1.18.2",
            "configuration_revision": "a" * 64,
            "scan_scope": (
                "Explicit Python paths: src/`name|x.py; "
                "src/quantum_toolkit/quantum_rt.py [click](https://example.test) "
                "![image](https://example.test/image.png) "
                "<https://autolink.example>\n- injected"
            ),
            "elapsed_seconds": 0.1,
            "finding_count": 0,
        }
    )

    summary = summary_path.read_text(encoding="utf-8")
    assert r"src/\`name\|x.py" in summary
    assert "src/quantum_toolkit/quantum_rt.py" in summary
    assert r"\[click\]\(https://example.test\)" in summary
    assert r"\!\[image\]\(https://example.test/image.png\)" in summary
    assert r"\<https://autolink.example\>" in summary
    assert r"\n- injected" in summary
    assert "\n- injected" not in summary


@pytest.mark.parametrize("scope", ["outside_checkout", "outside_src", "symlink_outside_checkout"])
def test_runner_rejects_paths_outside_repository_src_before_invoking_tools(
    scope: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_spec = importlib.util.find_spec("tools.run_mypy_advisory")
    assert module_spec is not None, "mypy advisory runner is missing"
    from tools import run_mypy_advisory

    src_path = tmp_path / "src"
    src_path.mkdir()
    if scope == "outside_checkout":
        invalid_path = tmp_path.parent / f"{tmp_path.name}-external.py"
        invalid_path.write_text("value: int = 1\n", encoding="utf-8")
        source_arg = str(invalid_path)
    elif scope == "outside_src":
        invalid_path = tmp_path / "tests" / "sample.py"
        invalid_path.parent.mkdir()
        invalid_path.write_text("value: int = 1\n", encoding="utf-8")
        source_arg = "tests/sample.py"
    else:
        target_path = tmp_path.parent / f"{tmp_path.name}-symlink-target.py"
        target_path.write_text("value: int = 1\n", encoding="utf-8")
        invalid_path = src_path / "external.py"
        try:
            invalid_path.symlink_to(target_path)
        except OSError as error:
            pytest.skip(f"file symlinks are unavailable: {error}")
        source_arg = "src/external.py"

    commands: list[list[str]] = []

    def fake_run_command(
        command: Sequence[str], *, cwd: Path | None = None
    ) -> dict[str, str | int | None]:
        commands.append(list(command))
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(run_mypy_advisory, "PROJECT_ROOT", tmp_path, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_mypy_advisory, "run_command", fake_run_command)

    config_path = tmp_path / "pyproject.toml"
    config_path.write_text("[tool.mypy]\npython_version = '3.11'\n", encoding="utf-8")
    output_dir = tmp_path / "output"
    result = run_mypy_advisory.main(
        [
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--paths",
            source_arg,
        ]
    )
    report = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))

    assert result == 0
    assert report["finding_count"] is None
    assert report["tool_errors"]["scope"]
    assert commands == []


def test_ci_summary_excludes_raw_diagnostics_and_remote_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_spec = importlib.util.find_spec("tools.run_mypy_advisory")
    assert module_spec is not None, "mypy advisory runner is missing"
    from tools import run_mypy_advisory

    (tmp_path / "pyproject.toml").write_text(
        "[tool.mypy]\npython_version = '3.11'\n", encoding="utf-8"
    )
    source_path = tmp_path / "src" / "quantum_toolkit" / "benchmark_provenance.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("value: int = 1\n", encoding="utf-8")
    output_dir = tmp_path / "tmp" / "mypy-advisory-local"
    summary_path = tmp_path / "step-summary.md"
    ci_dir = tmp_path / "tmp" / "mypy-advisory-ci" / "8100-1"
    remote_secret = "REMOTE_SECRET_SENTINEL"
    diagnostic_secret = "DIAGNOSTIC_SECRET_SENTINEL"
    remote_url = f"https://token:{remote_secret}@github.com/tylerdrakemusic/Quantum.git"

    def fake_run_command(
        command: Sequence[str], *, cwd: Path | None = None
    ) -> dict[str, str | int | None]:
        if command[-1:] == ["--version"]:
            return {"returncode": 0, "stdout": "mypy 1.18.2 (compiled: yes)\n", "stderr": ""}
        if list(command) == ["git", "rev-parse", "HEAD"]:
            return {"returncode": 0, "stdout": "abc1234\n", "stderr": ""}
        if list(command) == ["git", "remote", "get-url", "origin"]:
            return {"returncode": 0, "stdout": f"{remote_url}\n", "stderr": ""}
        if "-m" in command and "mypy" in command:
            return {
                "returncode": 1,
                "stdout": f"src/quantum_toolkit/benchmark_provenance.py:1: error: {diagnostic_secret} [assignment]\n",
                "stderr": "",
            }
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(run_mypy_advisory, "PROJECT_ROOT", tmp_path, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setenv("GITHUB_RUN_ID", "8100")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    monkeypatch.setattr(run_mypy_advisory, "run_command", fake_run_command)

    result = run_mypy_advisory.main(
        [
            "--config",
            "pyproject.toml",
            "--output-dir",
            str(output_dir),
            "--paths",
            "src/quantum_toolkit/benchmark_provenance.py",
        ]
    )

    ci_report_text = (ci_dir / "summary.json").read_text(encoding="utf-8")
    step_summary = summary_path.read_text(encoding="utf-8")
    assert result == 0
    assert json.loads(ci_report_text)["repository"] == "tylerdrakemusic/Quantum"
    assert json.loads(ci_report_text)["finding_count"] == 1
    for secret in (remote_secret, diagnostic_secret, remote_url):
        assert secret not in ci_report_text
        assert secret not in step_summary
