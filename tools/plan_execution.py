"""Deterministic provider-neutral execution planner dry run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from quantum_toolkit.execution_planner import NormalizedRequest, plan_execution
from quantum_toolkit.provider_fixtures import fixture_snapshots


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-json", required=True)
    parser.add_argument("--fixture", choices=("all", "ibm", "braket", "local"), default="all")
    parser.add_argument("--now-utc", required=True)
    parser.add_argument("--approved", action="store_true")
    parser.add_argument("--provenance", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    request = NormalizedRequest.from_dict(json.loads(args.request_json))
    provider = None if args.fixture == "all" else args.fixture
    result = plan_execution(
        request,
        fixture_snapshots(provider),
        now_utc=args.now_utc,
        approved=args.approved,
    ).to_dict()
    output: dict[str, Any] = {
        "planner_schema_version": "1.0",
        "request": request.to_dict(),
        "result": result,
    }
    serialized = json.dumps(output, sort_keys=True, separators=(",", ":"))
    print(serialized)
    if args.provenance is not None:
        args.provenance.write_text(serialized + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())