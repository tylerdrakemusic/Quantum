from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from time_crystal import (
    ComparativeRequest,
    EvidenceReport,
    NoiseConfig,
    Perturbation,
    ReplayValidationError,
    replay_evidence_report,
)
from time_crystal.protocol import FloquetIsingProtocol


ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "time_crystal"

_SPEC = importlib.util.spec_from_file_location(
    "gen_benchmark_dashboard",
    ROOT / "tools" / "gen_benchmark_dashboard.py",
)
assert _SPEC is not None and _SPEC.loader is not None
dashboard = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dashboard)


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _fixture_request() -> ComparativeRequest:
    return ComparativeRequest(
        protocol=FloquetIsingProtocol(
            system_size=3,
            periods=2,
            repetitions=1,
            pulse_angle=3.141592653589793,
            interaction_strength=0.15,
            disorder_strength=0.1,
        ),
        noise_models=(NoiseConfig(),),
        perturbations=(Perturbation("none"),),
        system_sizes=(3,),
        seed=23,
        max_cases=1,
        stable_pulse_boundaries=True,
    )


def test_valid_v1_fixture_replays_and_round_trips_deterministically() -> None:
    request = _fixture_request()
    encoded = _fixture("valid_report_v1.json")
    report = EvidenceReport.from_json(encoded)

    assert report.schema_version == "v1"
    assert replay_evidence_report(report, request).matched
    assert report.to_json() == encoded.rstrip("\n")


def test_tampered_evidence_fixture_fails_replay_closed() -> None:
    request = _fixture_request()
    report = EvidenceReport.from_json(_fixture("tampered_evidence.json"))

    with pytest.raises(ReplayValidationError, match="evidence"):
        replay_evidence_report(report, request)


def test_malformed_fixture_fails_closed() -> None:
    with pytest.raises(ValueError, match="malformed evidence report JSON"):
        EvidenceReport.from_json(_fixture("malformed_payload.json"))


def test_future_schema_fixture_fails_closed() -> None:
    with pytest.raises(ValueError, match="v2"):
        EvidenceReport.from_json(_fixture("future_schema_v2.json"))


def test_dashboard_keeps_title_history_and_unrelated_sections_on_report_failure(monkeypatch) -> None:
    def fail() -> str:
        raise RuntimeError("injected report-generation failure")

    monkeypatch.setattr(dashboard, "_build_time_crystal_panel", fail)
    rendered = dashboard.generate_html([], [], [], "2026-09-19T00:00:00Z", [], {})

    assert "Quantum Benchmark Dashboard" in rendered
    assert "Full Benchmark History" in rendered
    assert "VQE" in rendered
    assert "Unavailable" in rendered
    assert "injected report-generation failure" in rendered


def test_dashboard_keeps_title_history_and_unrelated_sections_on_replay_failure(monkeypatch) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("injected replay failure")

    monkeypatch.setattr(dashboard, "replay_evidence_report", fail)
    rendered = dashboard.generate_html([], [], [], "2026-09-19T00:00:00Z", [], {})

    assert "Quantum Benchmark Dashboard" in rendered
    assert "Full Benchmark History" in rendered
    assert "VQE" in rendered
    assert "Unavailable" in rendered
    assert "injected replay failure" in rendered
