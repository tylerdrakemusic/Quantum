"""Contract tests for the synthetic Quantum Kernel SVM feasibility prototype."""
from __future__ import annotations

import sys
import hashlib
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from quantum_kernel_svm import (  # noqa: E402
    EpisodeFixture,
    build_synthetic_episodes,
    run_feasibility_prototype,
    validate_approval_manifest,
    validate_no_leakage,
)


def test_grouped_holdout_is_reproducible_and_has_disjoint_subjects() -> None:
    episodes = build_synthetic_episodes(seed=7, subjects=12, episodes_per_subject=3)

    first = run_feasibility_prototype(episodes, seed=19, test_size=0.25)
    second = run_feasibility_prototype(episodes, seed=19, test_size=0.25)

    assert first.aggregate_json["counts"] == second.aggregate_json["counts"]
    assert first.aggregate_json["metrics"] == second.aggregate_json["metrics"]
    assert first.aggregate_json["holdout"]["train_subject_digests"] != second.aggregate_json["holdout"]["train_subject_digests"]
    assert set(first.aggregate_json["holdout"]["train_subject_digests"]).isdisjoint(
        first.aggregate_json["holdout"]["test_subject_digests"]
    )
    assert first.aggregate_json["class_balance"]["total"] == {"0": 18, "1": 18}


def test_subject_provenance_is_salted_full_digest_and_not_a_truncated_hash() -> None:
    episodes = build_synthetic_episodes(seed=7, subjects=12, episodes_per_subject=3)
    result = run_feasibility_prototype(episodes, seed=19, test_size=0.25)

    digests = result.aggregate_json["holdout"]["train_subject_digests"]
    assert all(len(digest) == hashlib.sha256().digest_size * 2 for digest in digests)
    unsalted_prefixes = {
        hashlib.sha256(episode.subject_id.encode("utf-8")).hexdigest()[:16]
        for episode in episodes
    }
    assert unsalted_prefixes.isdisjoint(digests)
    assert result.aggregate_json["config"]["provenance_digest"] == "sha256(subject_id + per-run random salt)"
    assert result.aggregate_json["config"]["provenance_salt_persisted"] is False


def test_approval_manifest_is_deny_by_default_and_requires_explicit_cli_approval() -> None:
    with pytest.raises(ValueError, match="explicit CLI approval"):
        validate_approval_manifest(None, cli_approved=False)

    manifest = {
        "schema_version": "v1",
        "fr_id": "FR-20260824-quantum-kernel-svm",
        "approval_id": "synthetic-approval-001",
        "purpose": "episode_binary_label_handoff",
        "approved": True,
    }
    validate_approval_manifest(manifest, cli_approved=True)


def test_approval_manifest_does_not_authorize_real_data() -> None:
    manifest = {
        "schema_version": "v1",
        "fr_id": "FR-20260824-quantum-kernel-svm",
        "approval_id": "synthetic-approval-001",
        "purpose": "episode_binary_label_handoff",
        "approved": True,
    }
    with pytest.raises(ValueError, match="synthetic-only"):
        validate_approval_manifest(manifest, cli_approved=True, synthetic_only=False)


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