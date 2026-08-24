from __future__ import annotations

import pytest

from src.qec_examples import (
    QECResult,
    run_repetition_code,
    run_surface_code,
)


def test_repetition_code_corrects_one_x_fault_with_structured_result() -> None:
    result = run_repetition_code(logical_bit=1, distance=3, faults=[(1, "X")])

    assert isinstance(result, QECResult)
    assert result.code == "repetition"
    assert result.syndrome == (1, 1)
    assert result.applied_correction == ((1, "X"),)
    assert result.logical_outcome == 1
    assert result.correctable is True
    assert result.reason == "single X fault corrected"


def test_surface_code_corrects_one_x_or_z_fault() -> None:
    x_result = run_surface_code(logical_bit=0, distance=3, faults=[(4, "X")])
    z_result = run_surface_code(logical_bit=1, distance=3, faults=[(4, "Z")])

    assert x_result.correctable is True
    assert x_result.logical_outcome == 0
    assert z_result.correctable is True
    assert z_result.logical_outcome == 1
    assert x_result.applied_correction == ((4, "X"),)
    assert z_result.applied_correction == ((4, "Z"),)


def test_repetition_code_reports_ambiguous_multi_fault_without_guessing() -> None:
    result = run_repetition_code(
        logical_bit=0,
        distance=3,
        faults=[(0, "X"), (1, "X")],
    )

    assert result.correctable is False
    assert result.applied_correction == ()
    assert result.logical_outcome is None
    assert "uncorrectable" in result.reason


def test_qec_inputs_are_validated_before_execution() -> None:
    with pytest.raises(ValueError):
        run_repetition_code(logical_bit=2, distance=3, faults=[])
    with pytest.raises(ValueError):
        run_repetition_code(logical_bit=0, distance=4, faults=[])
    with pytest.raises(ValueError):
        run_surface_code(logical_bit=0, distance=5, faults=[])
    with pytest.raises(ValueError):
        run_surface_code(logical_bit=0, distance=3, faults=[(0, "Y")])
    with pytest.raises(ValueError):
        run_repetition_code(logical_bit=0, distance=3, faults=[(3, "X")])


def test_strict_mode_raises_for_expected_uncorrectable_fault() -> None:
    with pytest.raises(ValueError, match="uncorrectable"):
        run_repetition_code(
            logical_bit=0,
            distance=3,
            faults=[(0, "X"), (1, "X")],
            strict=True,
        )


def test_aer_execution_is_deterministic_and_returns_counts() -> None:
    first = run_repetition_code(logical_bit=0, distance=3, faults=[(2, "X")])
    second = run_repetition_code(logical_bit=0, distance=3, faults=[(2, "X")])

    assert first.backend == "aer"
    assert first.counts == second.counts == (("000", 1),)


def test_surface_code_aer_execution_is_deterministic() -> None:
    first = run_surface_code(logical_bit=1, distance=3, faults=[(4, "Z")])
    second = run_surface_code(logical_bit=1, distance=3, faults=[(4, "Z")])

    assert first.backend == "aer"
    assert first.counts == second.counts == (("111111111", 1),)
