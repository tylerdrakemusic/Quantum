from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence


FR_ID = "FR-20261025-gradual-mypy-adoption"
_EXPECTED_MYPY_VERSION = "1.18.2"
DEFAULT_PATHS = ["src/quantum_toolkit/benchmark_provenance.py"]
PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ERROR_RE = re.compile(r"(?m)^.+?:\d+(?::\d+)?: error: .+?(?: \[(?P<code>[a-z0-9-]+)\])?$")
_REPOSITORY_RE = re.compile(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$")
_VERSION_RE = re.compile(r"^mypy (?P<version>\d+(?:\.\d+){1,2})(?: \(compiled: (?:yes|no)\))?$")


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def run_command(command: Sequence[str], *, cwd: Path | None = None) -> dict[str, Any]:
    """Capture command output, returning launch and timeout errors as results."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            cwd=cwd or PROJECT_ROOT,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "returncode": None,
            "stdout": _text(getattr(error, "stdout", "")),
            "stderr": _text(getattr(error, "stderr", "")) or str(error),
        }
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def _finding_counts(
    stdout: str, stderr: str, returncode: int | None
) -> tuple[int | None, dict[str, int]]:
    matches = list(_ERROR_RE.finditer(f"{stdout}\n{stderr}"))
    if returncode not in (0, 1):
        return None, {}
    if returncode == 1 and not matches:
        return None, {}
    codes = Counter(match.group("code") or "unknown" for match in matches)
    return len(matches), dict(sorted(codes.items()))


def _repository_slug(remote: str) -> str:
    match = _REPOSITORY_RE.search(remote.strip())
    return match.group(1) if match else "local"


def _scan_scope(paths: Sequence[str]) -> str:
    normalized = [Path(path).as_posix() for path in paths]
    return f"Explicit Python paths: {', '.join(normalized)}"


def _validated_scan_paths(paths: Sequence[str], root: Path) -> list[str]:
    resolved_root = root.resolve()
    src_root = (resolved_root / "src").resolve()
    try:
        src_root.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError from error

    normalized: list[str] = []
    for value in paths:
        path = Path(value)
        if not path.is_absolute():
            path = resolved_root / path
        try:
            resolved_path = path.resolve()
            resolved_path.relative_to(src_root)
        except (OSError, RuntimeError, ValueError) as error:
            raise ValueError from error
        if resolved_path.suffix.lower() != ".py" or not resolved_path.is_file():
            raise ValueError
        normalized.append(resolved_path.relative_to(resolved_root).as_posix())
    return normalized


def _command_error(result: dict[str, Any], allowed_codes: tuple[int, ...]) -> str | None:
    returncode = result["returncode"]
    stderr = _text(result["stderr"]).strip()
    if returncode is None:
        return stderr or "Command could not be started"
    if returncode not in allowed_codes:
        return stderr or f"Unexpected exit code {returncode}"
    return None


def _ci_output_dir() -> Path:
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    run_key = (
        f"{run_id}-{run_attempt}"
        if run_id.isdigit() and run_attempt.isdigit()
        else f"local-{os.getpid()}"
    )
    return PROJECT_ROOT / "tmp" / "mypy-advisory-ci" / run_key


def _escape_markdown(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("!", "\\!")
        .replace("<", "\\<")
        .replace(">", "\\>")
        .replace("|", "\\|")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def _ci_report(report: dict[str, Any]) -> dict[str, Any]:
    repository = str(report["repository"])
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        repository = "local"
    commit = str(report["commit"])
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit):
        commit = "unavailable"
    version = str(report["mypy_version"])
    if not _VERSION_RE.fullmatch(version):
        version = "unavailable"
    revision = str(report["configuration_revision"])
    if not re.fullmatch(r"[0-9a-f]{64}", revision):
        revision = "unavailable"
    return {
        "repository": repository,
        "commit": commit,
        "mypy_version": version,
        "configuration_revision": revision,
        "scan_scope": report["scan_scope"],
        "elapsed_seconds": report["elapsed_seconds"],
        "finding_count": report["finding_count"],
        "finding_counts_by_code": report["finding_counts_by_code"],
        "mypy_exit_code": report["mypy_exit_code"],
        "tool_errors": {name: bool(value) for name, value in report["tool_errors"].items()},
    }


def _append_step_summary(report: dict[str, Any]) -> None:
    lines = [
        f"## {FR_ID}: Quantum advisory mypy",
        "",
        f"- Repository: `{report['repository']}`",
        f"- Commit: `{report['commit']}`",
        f"- mypy: `{report['mypy_version']}`",
        f"- Configuration revision: `{report['configuration_revision']}`",
        f"- Scope: {_escape_markdown(str(report['scan_scope']))}",
        f"- Elapsed: {report['elapsed_seconds']:.3f} seconds",
        f"- Findings: `{report['finding_count']}`",
        "- Tool errors: `"
        + (
            ", ".join(name for name, error in report.get("tool_errors", {}).items() if error)
            or "none"
        )
        + "`",
        "- Advisory only: findings and tool errors do not gate CI; pytest remains required.",
        "",
    ]
    summary = "\n".join(lines)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary_file:
            summary_file.write(summary)
    print(summary, end="")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the non-gating advisory scan and write its reports."""
    parser = argparse.ArgumentParser(description="Run non-mutating advisory mypy checks.")
    parser.add_argument("--config", default="pyproject.toml")
    parser.add_argument("--output-dir", default="tmp/mypy-advisory-local")
    parser.add_argument("--paths", nargs="+", default=DEFAULT_PATHS)
    args = parser.parse_args(argv)

    root = PROJECT_ROOT.resolve()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path
    config_path = config_path.resolve()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    config_error = None
    try:
        config_path.relative_to(root)
        mypy_paths = _validated_scan_paths(args.paths, root)
    except (OSError, RuntimeError, ValueError):
        mypy_paths = []
        config_error = "configuration or scan paths must stay within the repository src tree"

    started = time.perf_counter()
    if config_error:
        version_result = {"returncode": None, "stdout": "", "stderr": ""}
        check_result = {"returncode": None, "stdout": "", "stderr": ""}
        commit_result = {
            "returncode": 0,
            "stdout": os.environ.get("GITHUB_SHA", "unavailable"),
            "stderr": "",
        }
        remote_result = {
            "returncode": 0,
            "stdout": os.environ.get("GITHUB_REPOSITORY", "local"),
            "stderr": "",
        }
    else:
        version_result = run_command([sys.executable, "-m", "mypy", "--version"], cwd=root)
        check_result = run_command(
            [
                sys.executable,
                "-m",
                "mypy",
                "--no-incremental",
                "--show-error-codes",
                "--no-error-summary",
                "--no-pretty",
                "--no-color-output",
                "--config-file",
                str(config_path),
                *mypy_paths,
            ],
            cwd=root,
        )
        commit_result = run_command(["git", "rev-parse", "HEAD"], cwd=root)
        remote_result = run_command(["git", "remote", "get-url", "origin"], cwd=root)
    elapsed_seconds = round(time.perf_counter() - started, 3)
    finding_count, finding_counts_by_code = _finding_counts(
        _text(check_result["stdout"]), _text(check_result["stderr"]), check_result["returncode"]
    )

    try:
        configuration_revision = hashlib.sha256(config_path.read_bytes()).hexdigest()
    except OSError as error:
        configuration_revision = "unavailable"
        config_error = config_error or str(error)

    remote = _text(remote_result["stdout"]).strip()
    repository = os.environ.get("GITHUB_REPOSITORY") or _repository_slug(remote)
    observed_version = _text(version_result["stdout"]).strip()
    version_match = _VERSION_RE.fullmatch(observed_version)
    version = observed_version if version_match else "unavailable"
    version_error = _command_error(version_result, (0,))
    if version_error is None:
        if version_match is None:
            version_error = "Could not parse mypy version output"
        elif version_match.group("version") != _EXPECTED_MYPY_VERSION:
            version_error = f"Expected mypy {_EXPECTED_MYPY_VERSION}, observed {observed_version}"
    tool_errors = {
        "version": version_error,
        "mypy": _command_error(check_result, (0, 1))
        or (
            "Could not parse mypy findings"
            if finding_count is None and check_result["returncode"] == 1
            else None
        ),
        "config": config_error,
        "commit": _command_error(commit_result, (0,)),
        "repository": _command_error(remote_result, (0,)),
        "scope": config_error,
    }
    report = {
        "fr_id": FR_ID,
        "repository": repository,
        "commit": _text(commit_result["stdout"]).strip() or "unavailable",
        "mypy_version": version,
        "configuration_revision": configuration_revision,
        "scan_scope": _scan_scope(mypy_paths)
        if not config_error
        else "Invalid scan scope rejected",
        "elapsed_seconds": elapsed_seconds,
        "finding_count": finding_count,
        "finding_counts_by_code": finding_counts_by_code,
        "mypy_exit_code": check_result["returncode"],
        "tool_errors": tool_errors,
    }

    for filename, content in (
        ("mypy.stdout.txt", check_result["stdout"]),
        ("mypy.stderr.txt", check_result["stderr"]),
        ("mypy-version.stdout.txt", version_result["stdout"]),
    ):
        (output_dir / filename).write_text(_text(content), encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    ci_dir = _ci_output_dir()
    ci_dir.mkdir(parents=True, exist_ok=True)
    ci_report = _ci_report(report)
    (ci_dir / "summary.json").write_text(json.dumps(ci_report, indent=2) + "\n", encoding="utf-8")
    _append_step_summary(ci_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
