from __future__ import annotations

import pytest

from quantum_toolkit.qec_validation import (
    QEC_VALIDATION_VERSION,
    QECValidationConfig,
    load_regression_baseline,
    decode_repetition_syndrome,
    replay_validation,
    run_validation_matrix,
    simulate_repeated_rounds,
    validate_regression_baseline,
)


def test_validation_config_requires_odd_distance_and_bounded_fault_rates() -> None:
    with pytest.raises(ValueError, match="odd"):
        QECValidationConfig(seed=7, distance=4, rounds=3)
    with pytest.raises(ValueError, match="data_pauli_x_rate"):
        QECValidationConfig(seed=7, distance=3, rounds=3, data_pauli_x_rate=1.1)
    with pytest.raises(ValueError, match="rounds"):
        QECValidationConfig(seed=7, distance=3, rounds=0)


def test_decoder_distinguishes_clean_single_fault_ambiguous_and_malformed() -> None:
    assert decode_repetition_syndrome((0, 0), distance=3).status == "clean"
    single = decode_repetition_syndrome((1, 1), distance=3)
    assert single.status == "corrected"
    assert single.correction == (1,)
    assert decode_repetition_syndrome((1, 0), distance=3).status == "corrected"
    assert decode_repetition_syndrome((1, 0, 1, 0), distance=5).status == "ambiguous"
    assert decode_repetition_syndrome((1, 1, 1, 1), distance=5).status == "uncorrectable"
    assert decode_repetition_syndrome((1,), distance=3).status == "malformed"


def test_repeated_round_simulation_emits_versioned_provenance_contract() -> None:
    result = simulate_repeated_rounds(
        QECValidationConfig(
            seed=20260906,
            distance=3,
            rounds=3,
            data_pauli_x_rate=0.001,
            syndrome_measurement_rate=0.005,
        )
    )

    assert result["validation_version"] == QEC_VALIDATION_VERSION
    assert result["seed"] == 20260906
    assert result["distance"] == 3
    assert result["rounds"] == 3
    assert result["data_pauli_x_rate"] == 0.001
    assert result["syndrome_measurement_rate"] == 0.005
    assert result["logical_outcome"] in (0, 1, None)
    assert isinstance(result["decoder_success"], bool)
    assert isinstance(result["logical_error"], bool)
    assert result["provenance"]["identity"]["family"] == "qec"
    assert result["provenance"]["configuration"]["todo_id"] == 552


def test_fixed_matrix_covers_all_approved_distances_rounds_and_fault_rates() -> None:
    results = run_validation_matrix(seed=20260906)

    assert len(results) == 3 * 3 * 3 * 3
    distances = [item["distance"] for item in results]
    assert set(distances) == {3, 5, 7}
    assert distances == ([3] * 27) + ([5] * 27) + ([7] * 27)
    assert {item["rounds"] for item in results} == {3, 5, 9}
    assert {
        item["data_pauli_x_rate"] for item in results
    } == {0.001, 0.005, 0.01}
    assert {
        item["syndrome_measurement_rate"] for item in results
    } == {0.001, 0.005, 0.01}


def test_checked_in_baseline_detects_tolerance_version_or_result_drift() -> None:
    baseline = load_regression_baseline()
    results = run_validation_matrix(seed=int(baseline["seed"]))

    assert validate_regression_baseline(results, baseline) == {
        "status": "pass",
        "tolerance_version": baseline["tolerance_version"],
    }
    changed = dict(baseline)
    changed["tolerance_version"] = "future-version"
    with pytest.raises(ValueError, match="tolerance"):
        validate_regression_baseline(results, changed)


def test_validation_replay_uses_normalized_qec_replay_contract() -> None:
    replay = replay_validation(QECValidationConfig(seed=41, distance=3, rounds=3))

    assert replay["family"] == "qec"
    assert replay["seed"] == 41
    assert replay["outcome"] == "pass"
    assert replay["tolerance_version"] == "2026-09-05"
    assert replay["result"]["validation"]["provenance"]["identity"]["family"] == "qec"