"""Run the repository pytest suite with optional xdist parallelism."""

from __future__ import annotations

import argparse
import configparser
import json
import shlex
import subprocess
import sys
from pathlib import Path


def _marker_expression(repo_root: Path) -> str | None:
    config = configparser.ConfigParser(interpolation=None)
    config.read(repo_root / "pytest.ini", encoding="utf-8")
    addopts = shlex.split(config.get("pytest", "addopts", fallback=""))
    try:
        return addopts[addopts.index("-m") + 1]
    except (ValueError, IndexError):
        return None


def _policy_exclusions(repo_root: Path) -> list[str]:
    with (repo_root / "tools" / "parallel_test_policy.json").open(encoding="utf-8") as policy_file:
        policy = json.load(policy_file)
    return policy.get("excluded_markers", [])


def _combined_marker_expression(repo_root: Path) -> str:
    configured = _marker_expression(repo_root)
    exclusions = [f"not {marker}" for marker in _policy_exclusions(repo_root)]
    policy_expression = " and ".join(exclusions)
    if configured and policy_expression:
        return f"({configured}) and ({policy_expression})"
    return configured or policy_expression


def build_command(*, parallel: bool, junitxml: Path | None, repo_root: Path | None = None) -> list[str]:
    """Build a pytest command while preserving repository configuration."""
    repo_root = repo_root or Path(__file__).parents[1]
    command = [sys.executable, "-m", "pytest", "--quiet", "--tb=short", "-rs"]
    command.extend(["-m", _combined_marker_expression(repo_root)])
    if parallel:
        command.extend(["-n", "auto"])
    if junitxml is not None:
        command.append(f"--junitxml={junitxml}")
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parallel", action="store_true", help="run with pytest-xdist workers")
    parser.add_argument("--junitxml", type=Path, help="write JUnit XML to this path")
    args = parser.parse_args()
    if args.junitxml is not None:
        args.junitxml.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.run(build_command(parallel=args.parallel, junitxml=args.junitxml), check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())