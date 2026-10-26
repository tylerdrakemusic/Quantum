from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


FR_ID = "FR-20261025-ruff-advisory-lint-rollout"


def run_command(command: Sequence[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        return {"returncode": None, "stdout": "", "stderr": str(error)}
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _repository_slug(remote: str) -> str:
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", remote.strip())
    return match.group(1) if match else "local"


def _relative_path(filename: str, root: Path) -> str:
    path = Path(filename)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return filename.replace("\\", "/")


def _check_findings(
    stdout: str, root: Path
) -> tuple[int | None, dict[str, int], list[str], str | None]:
    try:
        diagnostics = json.loads(stdout)
    except json.JSONDecodeError as error:
        return None, {}, [], f"Ruff check output was not valid JSON: {error}"
    if not isinstance(diagnostics, list):
        return None, {}, [], "Ruff check JSON output was not a diagnostic list"

    codes: Counter[str] = Counter()
    paths: set[str] = set()
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            continue
        code = diagnostic.get("code")
        filename = diagnostic.get("filename")
        if isinstance(code, str):
            codes[code] += 1
        if isinstance(filename, str):
            paths.add(_relative_path(filename, root))
    return len(diagnostics), dict(sorted(codes.items())), sorted(paths), None


def _format_findings(
    stdout: str, stderr: str, returncode: int | None
) -> tuple[int | None, list[str]]:
    combined = f"{stdout}\n{stderr}"
    summary_match = re.search(r"(?m)^(\d+) files? would be reformatted\b", combined)
    paths = sorted(
        {path.strip().replace("\\", "/") for path in re.findall(r"(?m)^---\s+(.+?)\s*$", stdout)}
    )
    if summary_match:
        return int(summary_match.group(1)), paths
    if returncode == 0:
        return 0, paths
    if paths:
        return len(paths), paths
    return None, paths


def _scan_scope(paths: Sequence[str]) -> str:
    if paths != ["."]:
        return f"Explicit Python paths: {', '.join(paths)}"
    return (
        "Repository-root Python files selected by Ruff's *.py include, respecting "
        "gitignore and the configured .worktrees, tmp, and output exclusions; "
        "non-Python files and database/runtime assets are not scanned."
    )


def _command_error(
    result: dict[str, Any], *, findings_known: bool, allowed_codes: tuple[int, ...]
) -> str | None:
    returncode = result["returncode"]
    stderr = str(result["stderr"]).strip()
    if returncode is None:
        return stderr or "Command could not be started"
    if returncode not in allowed_codes:
        return stderr or f"Unexpected exit code {returncode}"
    if stderr and not findings_known:
        return stderr
    return None


def _ci_output_dir() -> Path:
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if re.fullmatch(r"\d+", run_id) and re.fullmatch(r"\d+", run_attempt):
        run_key = f"{run_id}-{run_attempt}"
    else:
        run_key = f"local-{os.getpid()}"
    return Path("tmp/ruff-advisory-ci") / run_key


def _ci_report(report: dict[str, Any], paths: Sequence[str]) -> dict[str, Any]:
    version = str(report["ruff_version"])
    version_match = re.fullmatch(r"ruff 0\.17\.2", version)
    tool_errors = {name: bool(value) for name, value in report["tool_errors"].items()}
    if not version_match:
        tool_errors["version"] = True

    repository = str(report["repository"])
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        repository = "local"

    commit = str(report["commit"])
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit):
        commit = "unavailable"

    finding_counts = report["finding_counts"]
    check_by_code = {
        code: count
        for code, count in finding_counts["check_by_code"].items()
        if re.fullmatch(r"[A-Z][A-Z0-9]{0,15}", code)
    }
    scan_scope = (
        "Repository-root Python source scan"
        if paths == ["."]
        else f"Explicit Python path count: {len(paths)}"
    )
    return {
        "repository": repository,
        "commit": commit,
        "ruff_version": version_match.group(0) if version_match else "unavailable",
        "config_sha256": report["config"]["sha256"],
        "scan_scope": scan_scope,
        "elapsed_seconds": report["elapsed_seconds"],
        "finding_counts": {
            "check_total": finding_counts["check_total"],
            "check_by_code": check_by_code,
            "check_files": finding_counts["check_files"],
            "format_files": finding_counts["format_files"],
        },
        "command_exit_codes": report["command_exit_codes"],
        "tool_errors": tool_errors,
    }


def _append_step_summary(report: dict[str, Any]) -> None:
    counts = report["finding_counts"]
    errors = [name for name, has_error in report["tool_errors"].items() if has_error]
    lines = [
        f"## {FR_ID}: Quantum advisory Ruff",
        "",
        f"- Repository: `{report['repository']}`",
        f"- Scanned commit: `{report['commit']}`",
        f"- Ruff: `{report['ruff_version']}`",
        f"- Config SHA-256: `{report['config_sha256']}`",
        f"- Scope: {report['scan_scope']}",
        f"- Elapsed: {report['elapsed_seconds']['total']:.3f} seconds",
        f"- Findings: `ruff check` {counts['check_total']}; `ruff format --check` {counts['format_files']}",
        f"- Exit codes: version `{report['command_exit_codes']['version']}`, check `{report['command_exit_codes']['check']}`, format `{report['command_exit_codes']['format']}`",
        "- Advisory only: Ruff findings and command errors do not gate CI.",
        f"- Tool error categories: {', '.join(errors) if errors else 'none'}",
        "",
    ]
    summary = "\n".join(lines)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary_file:
            summary_file.write(summary)
    print(summary, end="")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run advisory, non-mutating Ruff checks.")
    parser.add_argument("--config", default="pyproject.toml")
    parser.add_argument("--output-dir", default="tmp/ruff-advisory-local")
    parser.add_argument("--paths", nargs="+", default=["."])
    args = parser.parse_args(argv)

    root = Path.cwd()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    version_result = run_command([sys.executable, "-m", "ruff", "--version"])
    check_started = time.perf_counter()
    check_result = run_command(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            args.config,
            "--output-format=json",
            *args.paths,
        ]
    )
    check_elapsed = round(time.perf_counter() - check_started, 3)
    format_started = time.perf_counter()
    format_result = run_command(
        [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--config",
            args.config,
            "--check",
            "--diff",
            *args.paths,
        ]
    )
    format_elapsed = round(time.perf_counter() - format_started, 3)

    check_total, check_by_code, check_paths, check_parse_error = _check_findings(
        str(check_result["stdout"]), root
    )
    format_total, format_paths = _format_findings(
        str(format_result["stdout"]),
        str(format_result["stderr"]),
        format_result["returncode"],
    )

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path
    try:
        config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
        config_error = None
    except OSError as error:
        config_hash = "unavailable"
        config_error = str(error)

    commit_result = run_command(["git", "rev-parse", "HEAD"])
    remote_result = run_command(["git", "remote", "get-url", "origin"])
    remote = str(remote_result["stdout"]).strip()
    repository = os.environ.get("GITHUB_REPOSITORY") or _repository_slug(remote)
    version = str(version_result["stdout"]).strip() or "unavailable"
    tool_errors = {
        "version": _command_error(version_result, findings_known=False, allowed_codes=(0,)),
        "check": check_parse_error
        or _command_error(
            check_result,
            findings_known=check_total is not None,
            allowed_codes=(0, 1),
        ),
        "format": _command_error(
            format_result,
            findings_known=format_total is not None,
            allowed_codes=(0, 1),
        ),
        "config": config_error,
        "commit": _command_error(commit_result, findings_known=False, allowed_codes=(0,)),
        "repository": _command_error(remote_result, findings_known=False, allowed_codes=(0,)),
    }

    report = {
        "fr_id": FR_ID,
        "repository": repository,
        "remote": remote or "unavailable",
        "commit": str(commit_result["stdout"]).strip() or "unavailable",
        "ruff_version": version,
        "config": {"path": Path(args.config).as_posix(), "sha256": config_hash},
        "scan_scope": _scan_scope(args.paths),
        "elapsed_seconds": {
            "check": check_elapsed,
            "format": format_elapsed,
            "total": round(check_elapsed + format_elapsed, 3),
        },
        "finding_counts": {
            "check_total": check_total,
            "check_by_code": check_by_code,
            "check_files": len(check_paths),
            "format_files": format_total,
        },
        "finding_paths": check_paths,
        "format_paths": format_paths,
        "command_exit_codes": {
            "version": version_result["returncode"],
            "check": check_result["returncode"],
            "format": format_result["returncode"],
        },
        "tool_errors": tool_errors,
    }

    outputs = {
        "ruff-check.json": check_result["stdout"],
        "ruff-check.stderr.txt": check_result["stderr"],
        "ruff-format.diff.txt": format_result["stdout"],
        "ruff-format.stderr.txt": format_result["stderr"],
        "ruff-version.stdout.txt": version_result["stdout"],
        "ruff-version.stderr.txt": version_result["stderr"],
    }
    for filename, content in outputs.items():
        (output_dir / filename).write_text(str(content), encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    ci_dir = _ci_output_dir()
    ci_dir.mkdir(parents=True, exist_ok=True)
    ci_report = _ci_report(report, args.paths)
    (ci_dir / "summary.json").write_text(json.dumps(ci_report, indent=2) + "\n", encoding="utf-8")
    _append_step_summary(ci_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
