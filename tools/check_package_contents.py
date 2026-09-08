"""Validate distribution contents and write a human-readable report."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path


REQUIRED_PATHS = {
    "quantum_rt.py",
    "quantum_toolkit/__init__.py",
    "quantum_toolkit/random.py",
    "utils/quantum_rt.py",
}
FORBIDDEN_MARKERS = (
    "IBM_CLOUD_API_KEY",
    "IBM_QUANTUM_INSTANCE",
    "livecache",
    "qbackups",
    "subject_profile",
    "medical_records",
    "genomics",
    ".env",
    ".db",
    ".sqlite",
)


def _artifact_paths(artifact: Path) -> set[str]:
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            return {name for name in archive.namelist() if not name.endswith("/")}
    if artifact.name.endswith(".tar.gz"):
        with tarfile.open(artifact, "r:gz") as archive:
            paths = {
                member.name.split("/", 1)[1]
                for member in archive.getmembers()
                if "/" in member.name
            }
            return {
                path.removeprefix("src/")
                for path in paths
            }
    raise ValueError(f"Unsupported distribution artifact: {artifact}")


def check_artifact(artifact: Path) -> None:
    paths = _artifact_paths(artifact)
    missing = sorted(REQUIRED_PATHS - paths)
    if missing:
        raise SystemExit(f"{artifact.name} is missing: {', '.join(missing)}")
    forbidden = sorted(
        path for path in paths if any(marker in path.lower() for marker in FORBIDDEN_MARKERS)
    )
    if forbidden:
        raise SystemExit(f"{artifact.name} contains forbidden paths: {', '.join(forbidden)}")
    print(f"{artifact.name}: package contents OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", nargs="+", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    lines = []
    try:
        for artifact in args.artifacts:
            check_artifact(artifact)
            lines.append(f"{artifact.name}: package contents OK")
    except SystemExit as exc:
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(f"FAILED: {exc}\n", encoding="utf-8")
        raise
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())