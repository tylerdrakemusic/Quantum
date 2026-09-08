"""Run the documented public API smoke test from an installed distribution."""

from __future__ import annotations

import warnings
import argparse


PUBLIC_API = (
    "qRandom",
    "qRax",
    "qhoice",
    "quuffle",
    "qsample",
    "qpermute",
    "qRandomBool",
    "qRandomBitstring",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=str)
    args = parser.parse_args()
    import quantum_toolkit

    assert quantum_toolkit.__all__ == PUBLIC_API
    assert all(callable(getattr(quantum_toolkit, name)) for name in PUBLIC_API)
    assert 0 <= quantum_toolkit.qRandom() < 1
    assert 2 <= quantum_toolkit.qRax(2, 2) <= 2
    assert quantum_toolkit.qhoice(["a"]) == "a"
    shuffled = [1, 2, 3]
    assert quantum_toolkit.quuffle(shuffled) is None
    assert sorted(shuffled) == [1, 2, 3]
    assert len(quantum_toolkit.qsample([1, 2, 3], 2)) == 2
    assert sorted(quantum_toolkit.qpermute([1, 2, 3])) == [1, 2, 3]
    assert isinstance(quantum_toolkit.qRandomBool(), bool)
    assert len(quantum_toolkit.qRandomBitstring(8)) == 8

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import quantum_rt

    assert any(item.category is DeprecationWarning for item in caught)
    assert quantum_rt.qRandom is quantum_toolkit.qRandom
    result = "quantum_toolkit and quantum_rt API smoke OK\n"
    print(result, end="")
    if args.report:
        from pathlib import Path

        report = Path(args.report)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(result, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())