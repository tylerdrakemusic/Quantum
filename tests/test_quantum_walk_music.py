"""Tests for quantum_walk_music.py — FR-20260518-quantum-walk-music"""
from __future__ import annotations

import sys
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Path setup — import the module under test from project src/
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT / "src" / "utils"))

import quantum_walk_music as qwm   # noqa: E402


# ---------------------------------------------------------------------------
# test_scale_definitions
# ---------------------------------------------------------------------------


def test_scale_definitions() -> None:
    """All 5 scales have the correct semitone intervals."""
    assert qwm.SCALES["chromatic"]        == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    assert qwm.SCALES["pentatonic"]       == [0, 2, 4, 7, 9]
    assert qwm.SCALES["major"]            == [0, 2, 4, 5, 7, 9, 11]
    assert qwm.SCALES["minor"]            == [0, 2, 3, 5, 7, 8, 10]
    assert qwm.SCALES["circle_of_fifths"] == [0, 7, 2, 9, 4, 11, 6, 1, 8, 3, 10, 5]


# ---------------------------------------------------------------------------
# test_note_to_freq
# ---------------------------------------------------------------------------


def test_note_to_freq() -> None:
    """MIDI 69 (A4) must equal 440 Hz; MIDI 60 (C4) ≈ 261.63 Hz."""
    assert abs(qwm.note_to_freq(69) - 440.0) < 0.001
    assert abs(qwm.note_to_freq(60) - 261.626) < 0.01


def test_note_to_freq_octaves() -> None:
    """Each octave up doubles the frequency."""
    freq_c4 = qwm.note_to_freq(60)   # C4
    freq_c5 = qwm.note_to_freq(72)   # C5
    assert abs(freq_c5 / freq_c4 - 2.0) < 1e-9


# ---------------------------------------------------------------------------
# test_parse_key
# ---------------------------------------------------------------------------


def test_parse_key_naturals() -> None:
    """Natural note letters map to correct semitones."""
    expected = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    for letter, semitone in expected.items():
        assert qwm.parse_key(letter) == semitone


def test_parse_key_sharps_and_flats() -> None:
    """Sharp (#) and flat (b) accidentals are applied correctly."""
    assert qwm.parse_key("F#") == 6
    assert qwm.parse_key("Bb") == 10
    assert qwm.parse_key("C#") == 1
    assert qwm.parse_key("Eb") == 3


# ---------------------------------------------------------------------------
# test_position_to_midi
# ---------------------------------------------------------------------------


def test_position_to_midi_pentatonic() -> None:
    """Walk positions map to expected MIDI notes for pentatonic scale from C4."""
    scale     = qwm.SCALES["pentatonic"]   # [0, 2, 4, 7, 9]
    root_midi = 60                          # C4
    # Octave 0: positions 0..4
    assert qwm.position_to_midi(0, scale, root_midi) == 60   # C4
    assert qwm.position_to_midi(1, scale, root_midi) == 62   # D4
    assert qwm.position_to_midi(4, scale, root_midi) == 69   # A4
    # Octave 1: position 5 → C5
    assert qwm.position_to_midi(5, scale, root_midi) == 72   # C5
    assert qwm.position_to_midi(9, scale, root_midi) == 81   # A5


# ---------------------------------------------------------------------------
# test_walk_output_files — mock Aer, verify .wav and .mid creation
# ---------------------------------------------------------------------------


def _make_mock_backend(n_pos_qubits: int = qwm.N_POS_QUBITS) -> MagicMock:
    """Return a mock AerSimulator that returns uniform counts."""
    n_positions = 2 ** n_pos_qubits
    shots = qwm.SHOTS
    counts_per_pos = shots // n_positions
    mock_counts = {
        format(i, f"0{n_pos_qubits}b"): counts_per_pos
        for i in range(n_positions)
    }
    mock_result  = MagicMock()
    mock_result.get_counts.return_value = mock_counts
    mock_job     = MagicMock()
    mock_job.result.return_value = mock_result
    mock_backend = MagicMock()
    mock_backend.run.return_value = mock_job
    return mock_backend


def test_walk_output_files(tmp_path: Path) -> None:
    """Mock Aer, verify .wav and .mid files are created with content."""
    mock_backend = _make_mock_backend()

    with (
        patch.object(qwm, "AerSimulator", return_value=mock_backend),
        patch("quantum_walk_music.transpile", return_value=MagicMock()),
    ):
        probs = qwm.run_quantum_walk(4, shots=qwm.SHOTS, use_qpu=False)

    # Probabilities should sum to 1 (uniform across 16 positions)
    assert abs(sum(probs.values()) - 1.0) < 0.05

    # WAV creation
    wav_path = tmp_path / "test.wav"
    audio    = np.sin(np.linspace(0, 2 * np.pi, 44100))
    qwm.write_wav(audio, wav_path)
    assert wav_path.exists()
    assert wav_path.stat().st_size > 44   # at minimum a WAV header
    # Verify WAV is readable
    with wave.open(str(wav_path), "r") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == qwm.SAMPLE_RATE

    # MIDI creation
    mid_path = tmp_path / "test.mid"
    qwm.write_midi([(60, 1.0), (62, 0.5), (64, 1.0)], 120, mid_path)
    assert mid_path.exists()
    assert mid_path.stat().st_size > 0


# ---------------------------------------------------------------------------
# test_html_generated
# ---------------------------------------------------------------------------


def test_html_generated(tmp_path: Path) -> None:
    """HTML output contains Chart.js CDN link, datasets, and title."""
    n = qwm.N_POSITIONS
    uniform = 1.0 / n
    quantum_probs   = {i: uniform for i in range(n)}
    classical_probs = {i: uniform for i in range(n)}
    params = {
        "steps": 32, "scale": "pentatonic",
        "key": "C", "bpm": 120, "octave": 4, "shots": 1024,
    }

    html_path = tmp_path / "test.html"
    qwm.write_html(quantum_probs, classical_probs, params, html_path)

    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")

    assert "chart.js" in content.lower()
    assert "Quantum walk" in content
    assert "Classical random walk" in content
    assert "Position Distribution" in content
    assert "steps=32" in content


# ---------------------------------------------------------------------------
# test_quantum_walk_circuit_structure
# ---------------------------------------------------------------------------


def test_quantum_walk_circuit_structure() -> None:
    """Walk circuit has correct register sizes and measurement targets."""
    qc = qwm.build_quantum_walk_circuit(n_steps=2)
    # 1 coin + N_POS_QUBITS position qubits
    assert qc.num_qubits == 1 + qwm.N_POS_QUBITS
    assert qc.num_clbits == qwm.N_POS_QUBITS
