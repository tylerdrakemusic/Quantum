"""Read-only operator command for quantum cache integrity verification."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src" / "utils"))

import cache_integrity


def main(argv: list[str] | None = None) -> int:
    """Verify a cache and print a compact status line."""
    parser = argparse.ArgumentParser(description="Verify the quantum cache without modifying it")
    parser.add_argument(
        "--cache",
        type=Path,
        default=_ROOT / "src" / "data" / "liveCache" / "ty_string_cache.txt",
    )
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        status = cache_integrity.verify_cache(args.cache, args.manifest)
    except (FileNotFoundError, OSError) as exc:
        print(f"cache verification unavailable: {exc}")
        return 2
    print(
        " ".join(
            [
                f"verified={str(status['valid']).lower()}",
                f"source={status['source']}",
                f"bit_count={status['bit_count']}",
                f"malformed_lines={status['malformed_lines']}",
            ]
        )
    )
    return 0 if status["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())