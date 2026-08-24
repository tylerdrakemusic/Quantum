"""Contract tests for the synthetic Quantum Kernel SVM feasibility prototype."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from quantum_kernel_svm import (  # noqa: E402
    EpisodeFixture,
    build_synthetic_episodes,
    run_feasibility_prototype,
    validate_no_leakage,
)


def test_grouped_holdout_is_reproducible_and_has_disjoint_subjects() -> None:
    episodes = build_synthetic_episodes(seed=7, subjects=12, episodes_per_subject=3)

    first = run_feasibility_prototype(episodes, seed=19, test_size=0.25)
    second = run_feasibility_prototype(episodes, seed=19, test_size=0.25)

    assert first.aggregate_json == second.aggregate_json
    assert set(first.aggregate_json["holdout"]["train_subject_hashes"]).isdisjoint(
        first.aggregate_json["holdout"]["test_subject_hashes"]
    )
    assert first.aggregate_json["class_balance"]["total"] == {"0": 18, "1": 18}


def test_leakage_check_rejects_subject_feature_overlap() -> None:
    episodes = [
        EpisodeFixture("subject-a", "episode-1", np.array([0.1, 0.2]), 0),
        EpisodeFixture("subject-a", "episode-2", np.array([0.2, 0.3]), 1),
    ]

    with pytest.raises(ValueError, match="subject leakage"):
        validate_no_leakage(episodes, train_episode_ids={"episode-1"}, test_episode_ids={"episode-2"})


def test_persisted_evidence_contains_aggregates_but_no_rows_or_predictions(tmp_path: Path) -> None:
    episodes = build_synthetic_episodes(seed=3, subjects=8, episodes_per_subject=2)
    result = run_feasibility_prototype(episodes, seed=5, test_size=0.25)
    path = result.write_evidence(tmp_path)

    evidence = path.read_text(encoding="utf-8")
    assert "episode-" not in evidence
    assert "prediction" not in evidence.lower()
    assert "metrics" in evidence
    assert "config" in evidence