"""Synthetic, local-only Quantum Kernel SVM feasibility experiment."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score
from sklearn.model_selection import StratifiedShuffleSplit
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC


@dataclass(frozen=True)
class EpisodeFixture:
    """An in-memory synthetic episode; it is never serialized."""

    subject_id: str
    episode_id: str
    features: np.ndarray
    label: int


@dataclass(frozen=True)
class PrototypeResult:
    aggregate_json: dict[str, Any]
    _raw: dict[str, Any]

    def write_evidence(self, directory: Path) -> Path:
        """Write only redacted aggregate evidence and return its path."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "quantum_kernel_svm_evidence.json"
        path.write_text(json.dumps(self.aggregate_json, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path


def build_synthetic_episodes(seed: int = 7, subjects: int = 12, episodes_per_subject: int = 3) -> list[EpisodeFixture]:
    """Build balanced episode-level fixtures with subject-correlated signals."""
    generator = np.random.default_rng(seed)
    episodes: list[EpisodeFixture] = []
    for subject_index in range(subjects):
        label = subject_index % 2
        center = np.array([1.0, -0.8, 0.5]) if label else np.array([-1.0, 0.8, -0.5])
        for episode_index in range(episodes_per_subject):
            features = center + generator.normal(0.0, 0.28, size=3)
            episodes.append(EpisodeFixture(
                subject_id=f"subject-{subject_index:03d}",
                episode_id=f"episode-{subject_index:03d}-{episode_index:02d}",
                features=features,
                label=label,
            ))
    return episodes


def validate_no_leakage(
    episodes: list[EpisodeFixture], train_episode_ids: set[str], test_episode_ids: set[str]
) -> None:
    """Reject episode or subject overlap between train and test partitions."""
    by_id = {episode.episode_id: episode for episode in episodes}
    missing = (train_episode_ids | test_episode_ids) - by_id.keys()
    if missing:
        raise ValueError(f"unknown episode ids: {sorted(missing)}")
    if train_episode_ids & test_episode_ids:
        raise ValueError("episode leakage: train and test episode ids overlap")
    train_subjects = {by_id[episode_id].subject_id for episode_id in train_episode_ids}
    test_subjects = {by_id[episode_id].subject_id for episode_id in test_episode_ids}
    if train_subjects & test_subjects:
        raise ValueError("subject leakage: train and test subjects overlap")


def _subject_hash(subject_id: str) -> str:
    return hashlib.sha256(subject_id.encode("utf-8")).hexdigest()[:16]


def _aer_statevector(features: np.ndarray) -> np.ndarray:
    """Prepare one feature state and simulate it with local Qiskit Aer."""
    from qiskit import QuantumCircuit
    from qiskit_aer import AerSimulator

    circuit = QuantumCircuit(len(features))
    for index, value in enumerate(features):
        circuit.ry(float(value), index)
    for index in range(len(features) - 1):
        circuit.cx(index, index + 1)
    circuit.save_statevector()
    result = AerSimulator(method="statevector").run(circuit, shots=1).result()
    return np.asarray(result.get_statevector(circuit))


def _fidelity_kernel(train_features: np.ndarray, other_features: np.ndarray) -> np.ndarray:
    train_states = [_aer_statevector(row) for row in train_features]
    other_states = [_aer_statevector(row) for row in other_features]
    return np.asarray([[abs(np.vdot(left, right)) ** 2 for right in other_states] for left in train_states])


def _metrics(labels: np.ndarray, predictions: np.ndarray) -> dict[str, float]:
    return {
        "accuracy": float(accuracy_score(labels, predictions)),
        "balanced_accuracy": float(balanced_accuracy_score(labels, predictions)),
        "f1": float(f1_score(labels, predictions, zero_division=0)),
    }


def run_feasibility_prototype(
    episodes: list[EpisodeFixture], seed: int = 19, test_size: float = 0.25
) -> PrototypeResult:
    """Run grouped stratified quantum/classical SVM comparisons in memory."""
    if not episodes:
        raise ValueError("episodes must not be empty")
    subjects = sorted({episode.subject_id for episode in episodes})
    subject_labels = np.asarray([next(item.label for item in episodes if item.subject_id == subject) for subject in subjects])
    splitter = StratifiedShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
    train_subject_indices, test_subject_indices = next(splitter.split(subjects, subject_labels))
    train_subjects = {subjects[index] for index in train_subject_indices}
    test_subjects = {subjects[index] for index in test_subject_indices}
    train = [episode for episode in episodes if episode.subject_id in train_subjects]
    test = [episode for episode in episodes if episode.subject_id in test_subjects]
    validate_no_leakage(episodes, {episode.episode_id for episode in train}, {episode.episode_id for episode in test})

    train_features = np.asarray([episode.features for episode in train])
    test_features = np.asarray([episode.features for episode in test])
    train_labels = np.asarray([episode.label for episode in train])
    test_labels = np.asarray([episode.label for episode in test])
    scaler = StandardScaler().fit(train_features)
    scaled_train = scaler.transform(train_features)
    scaled_test = scaler.transform(test_features)

    quantum_train_kernel = _fidelity_kernel(scaled_train, scaled_train)
    quantum_test_kernel = _fidelity_kernel(scaled_test, scaled_train)
    quantum_model = SVC(kernel="precomputed", C=1.0).fit(quantum_train_kernel, train_labels)
    quantum_labels = quantum_model.predict(quantum_test_kernel)
    classical_model = SVC(kernel="rbf", C=1.0, gamma="scale").fit(scaled_train, train_labels)
    classical_labels = classical_model.predict(scaled_test)

    class_balance = {
        "total": {str(label): int(sum(episode.label == label for episode in episodes)) for label in (0, 1)},
        "train": {str(label): int(sum(episode.label == label for episode in train)) for label in (0, 1)},
        "test": {str(label): int(sum(episode.label == label for episode in test)) for label in (0, 1)},
    }
    aggregate = {
        "config": {
            "backend": "qiskit-aer",
            "kernel": "statevector-fidelity",
            "classical_comparator": "sklearn-rbf-svc",
            "seed": seed,
            "test_size": test_size,
            "fixture_seed": None,
            "raw_data_persisted": False,
            "row_level_outputs_persisted": False,
        },
        "counts": {"subjects": len(subjects), "episodes": len(episodes), "train_episodes": len(train), "test_episodes": len(test)},
        "holdout": {
            "strategy": "grouped-stratified-by-subject",
            "train_subject_hashes": sorted(_subject_hash(subject) for subject in train_subjects),
            "test_subject_hashes": sorted(_subject_hash(subject) for subject in test_subjects),
        },
        "class_balance": class_balance,
        "metrics": {"quantum_kernel_svm": _metrics(test_labels, quantum_labels), "classical_rbf_svm": _metrics(test_labels, classical_labels)},
        "error_analysis": {
            "quantum_kernel_svm": {"errors": int(np.sum(test_labels != quantum_labels))},
            "classical_rbf_svm": {"errors": int(np.sum(test_labels != classical_labels))},
        },
    }
    raw = {"train_subjects": train_subjects, "test_subjects": test_subjects}
    return PrototypeResult(aggregate_json=aggregate, _raw=raw)