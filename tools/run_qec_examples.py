"""Run the local QEC examples without IBM credentials or hardware."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.qec_examples import run_repetition_code, run_surface_code


def main() -> None:
    """Print deterministic repetition and surface-code example results."""
    results = [
        run_repetition_code(logical_bit=1, distance=3, faults=[(1, "X")]),
        run_surface_code(logical_bit=0, distance=3, faults=[(4, "Z")]),
    ]
    print(json.dumps([asdict(result) for result in results], indent=2))


if __name__ == "__main__":
    main()