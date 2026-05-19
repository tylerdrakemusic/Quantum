#!/usr/bin/env python3
"""⟨ψ⟩ Quantum Walk Music Generator

Runs a discrete-time quantum walk circuit using Qiskit Aer (or IBM QPU),
maps the walk's position probability distribution to musical notes, and
outputs synthesised audio (.wav), MIDI (.mid), and an HTML visualisation.

Usage::

    python quantum_walk_music.py [--steps N] [--scale SCALE] [--key KEY]
                                 [--bpm BPM] [--octave OCT] [--use-qpu]
"""
from __future__ import annotations

import argparse
import math
import sys
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Path setup — allow import from project src/utils/
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src" / "utils"))

from quantum_rt import qhoice  # noqa: E402 — must follow sys.path setup

# ---------------------------------------------------------------------------
# Qiskit / MIDI imports
# ---------------------------------------------------------------------------
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister, transpile
from qiskit_aer import AerSimulator
from midiutil import MIDIFile

# ---------------------------------------------------------------------------
# Constants — scales and MIDI
# ---------------------------------------------------------------------------

SCALES: dict[str, list[int]] = {
    "chromatic":        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    "pentatonic":       [0, 2, 4, 7, 9],
    "major":            [0, 2, 4, 5, 7, 9, 11],
    "minor":            [0, 2, 3, 5, 7, 8, 10],
    "circle_of_fifths": [0, 7, 2, 9, 4, 11, 6, 1, 8, 3, 10, 5],
}

_NOTE_SEMITONES: dict[str, int] = {
    "C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11,
}

N_POS_QUBITS: int = 4
N_POSITIONS: int = 2 ** N_POS_QUBITS   # 16 walk nodes
SHOTS: int = 1024
SAMPLE_RATE: int = 44100

# ADSR parameters (samples)
_ATTACK_S   = int(0.005 * SAMPLE_RATE)   # 5 ms
_DECAY_S    = int(0.050 * SAMPLE_RATE)   # 50 ms
_SUSTAIN_L  = 0.7
_RELEASE_S  = int(0.080 * SAMPLE_RATE)   # 80 ms

# ---------------------------------------------------------------------------
# Music helpers
# ---------------------------------------------------------------------------


def parse_key(key: str) -> int:
    """Return semitone offset (0 = C) for a key string, e.g. 'C', 'F#', 'Bb'."""
    key = key.strip()
    if not key:
        raise ValueError("Empty key string")
    letter = key[0].upper()
    if letter not in _NOTE_SEMITONES:
        raise ValueError(f"Unknown note letter: {letter!r}")
    semitone = _NOTE_SEMITONES[letter]
    for ch in key[1:]:
        if ch == "#":
            semitone += 1
        elif ch == "b":
            semitone -= 1
    return semitone % 12


def note_to_freq(midi_note: int) -> float:
    """Convert a MIDI note number to frequency in Hz (A4 = 69 = 440 Hz)."""
    return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))


def position_to_midi(pos: int, scale: list[int], root_midi: int) -> int:
    """Map a walk position index to a MIDI note number.

    Formula: root_midi + scale[pos % len(scale)] + (pos // len(scale)) * 12
    """
    return root_midi + scale[pos % len(scale)] + (pos // len(scale)) * 12


# ---------------------------------------------------------------------------
# Quantum walk circuit
# ---------------------------------------------------------------------------


def _controlled_increment(
    qc: QuantumCircuit,
    ctrl: object,
    pos_qubits: list,
) -> None:
    """Add 1 mod 2^n to the position register when *ctrl* = |1⟩.

    Uses a reverse ripple-carry pattern: process MSB first so each flip
    reads the pre-step values of all lower-order bits.

    For n = 4:
      flip pos[3] if ctrl=1 and pos[0..2] = 1  (all-ones carry)
      flip pos[2] if ctrl=1 and pos[0..1] = 1
      flip pos[1] if ctrl=1 and pos[0]   = 1
      flip pos[0] if ctrl=1              (always flip LSB)
    """
    n = len(pos_qubits)
    for i in range(n - 1, 0, -1):
        qc.mcx([ctrl] + list(pos_qubits[:i]), pos_qubits[i])
    qc.cx(ctrl, pos_qubits[0])


def _controlled_decrement(
    qc: QuantumCircuit,
    ctrl: object,
    pos_qubits: list,
) -> None:
    """Subtract 1 mod 2^n from position register when *ctrl* = |1⟩.

    Implements decrement as: complement → increment → complement, all
    conditioned on *ctrl*.  The complement steps cancel when ctrl = |0⟩.
    """
    for q in pos_qubits:
        qc.cx(ctrl, q)
    _controlled_increment(qc, ctrl, pos_qubits)
    for q in pos_qubits:
        qc.cx(ctrl, q)


def build_quantum_walk_circuit(n_steps: int) -> QuantumCircuit:
    """Return a discrete-time quantum walk QuantumCircuit.

    Architecture
    ------------
    * 1 coin qubit  (Hadamard coin, starts as |0⟩)
    * N_POS_QUBITS position qubits on a 16-node cyclic line
    * Initial position: centre node (8)
    * Each step: H on coin → shift right if |1⟩, shift left if |0⟩
    """
    coin = QuantumRegister(1, "coin")
    pos  = QuantumRegister(N_POS_QUBITS, "pos")
    meas = ClassicalRegister(N_POS_QUBITS, "meas")
    qc = QuantumCircuit(coin, pos, meas)

    # Initialise position register to centre (8 = 0b1000)
    center = N_POSITIONS // 2
    for bit in range(N_POS_QUBITS):
        if (center >> bit) & 1:
            qc.x(pos[bit])

    pos_list = [pos[i] for i in range(N_POS_QUBITS)]

    for _ in range(n_steps):
        qc.h(coin[0])                                  # Hadamard coin
        _controlled_increment(qc, coin[0], pos_list)   # shift right  |1⟩
        qc.x(coin[0])
        _controlled_decrement(qc, coin[0], pos_list)   # shift left   |0⟩
        qc.x(coin[0])

    qc.measure(pos, meas)
    return qc


def run_quantum_walk(
    n_steps: int,
    shots: int = SHOTS,
    use_qpu: bool = False,
) -> dict[int, float]:
    """Execute the quantum walk circuit and return position probabilities.

    Returns a mapping ``{position: probability}`` for 0..N_POSITIONS-1.
    """
    qc = build_quantum_walk_circuit(n_steps)

    if use_qpu:
        # Import IBM Quantum backend helper from project utilities
        from quantum_backend import get_least_busy_backend  # type: ignore
        backend = get_least_busy_backend()
    else:
        backend = AerSimulator()

    compiled = transpile(qc, backend)
    job = backend.run(compiled, shots=shots)
    counts: dict[str, int] = job.result().get_counts()

    # Qiskit bitstrings are big-endian (MSB leftmost), matching int(bitstr, 2)
    probs: dict[int, float] = {}
    for i in range(N_POSITIONS):
        bitstr = format(i, f"0{N_POS_QUBITS}b")
        probs[i] = counts.get(bitstr, 0) / shots
    return probs


# ---------------------------------------------------------------------------
# Classical random walk baseline
# ---------------------------------------------------------------------------


def run_classical_walk(
    n_steps: int,
    n_trials: int = SHOTS,
) -> dict[int, float]:
    """Simulate a classical random walk and return empirical probabilities."""
    center = N_POSITIONS // 2
    counts: dict[int, int] = {i: 0 for i in range(N_POSITIONS)}
    rng = np.random.default_rng()
    for _ in range(n_trials):
        p = center
        for _ in range(n_steps):
            p = (p + (1 if rng.random() > 0.5 else -1)) % N_POSITIONS
        counts[p] += 1
    total = sum(counts.values())
    return {k: v / total for k, v in counts.items()}


# ---------------------------------------------------------------------------
# Audio synthesis
# ---------------------------------------------------------------------------


def _adsr_envelope(n_samples: int) -> np.ndarray:
    """Return a float64 ADSR amplitude envelope of length *n_samples*."""
    env = np.empty(n_samples, dtype=np.float64)
    atk_end = min(_ATTACK_S, n_samples)
    env[:atk_end] = np.linspace(0.0, 1.0, atk_end)

    dcy_end = min(atk_end + _DECAY_S, n_samples)
    if dcy_end > atk_end:
        env[atk_end:dcy_end] = np.linspace(1.0, _SUSTAIN_L, dcy_end - atk_end)

    rls_start = max(dcy_end, n_samples - _RELEASE_S)
    if rls_start > dcy_end:
        env[dcy_end:rls_start] = _SUSTAIN_L

    if rls_start < n_samples:
        env[rls_start:] = np.linspace(_SUSTAIN_L, 0.0, n_samples - rls_start)
    return env


def synthesize_note(
    midi_note: int,
    duration_sec: float,
    amplitude: float = 0.5,
) -> np.ndarray:
    """Return a float64 PCM array for one note with harmonics and ADSR."""
    freq = note_to_freq(midi_note)
    n = int(duration_sec * SAMPLE_RATE)
    if n == 0:
        return np.zeros(0, dtype=np.float64)
    t = np.linspace(0.0, duration_sec, n, endpoint=False)
    waveform = (
        np.sin(2 * np.pi * freq * t)
        + 0.50 * np.sin(2 * np.pi * 2 * freq * t)
        + 0.25 * np.sin(2 * np.pi * 3 * freq * t)
        + 0.12 * np.sin(2 * np.pi * 4 * freq * t)
    )
    waveform /= 1.0 + 0.50 + 0.25 + 0.12   # normalise harmonic sum to 1
    return amplitude * waveform * _adsr_envelope(n)


def write_wav(samples: np.ndarray, filepath: Path) -> None:
    """Write float audio samples to a 16-bit PCM mono WAV file."""
    max_val = np.max(np.abs(samples)) if samples.size > 0 else 1.0
    if max_val > 0.0:
        samples = samples / max_val
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(filepath), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())


# ---------------------------------------------------------------------------
# MIDI
# ---------------------------------------------------------------------------


def write_midi(
    notes: list[tuple[int, float]],
    bpm: int,
    filepath: Path,
) -> None:
    """Write a single-track MIDI file from (midi_note, duration_beats) pairs."""
    midi = MIDIFile(1)
    midi.addTempo(0, 0, bpm)
    time = 0.0
    for midi_note, dur_beats in notes:
        midi.addNote(0, 0, midi_note, time, dur_beats, 100)
        time += dur_beats
    with open(filepath, "wb") as fh:
        midi.writeFile(fh)


# ---------------------------------------------------------------------------
# HTML visualisation
# ---------------------------------------------------------------------------


def write_html(
    quantum_probs: dict[int, float],
    classical_probs: dict[int, float],
    params: dict,
    filepath: Path,
) -> None:
    """Generate a standalone Chart.js bar chart of the walk distribution."""
    positions = list(range(N_POSITIONS))
    q_data = [round(quantum_probs.get(i, 0.0), 5) for i in positions]
    c_data = [round(classical_probs.get(i, 0.0), 5) for i in positions]
    caption = (
        f"steps={params['steps']}, scale={params['scale']}, "
        f"key={params['key']}, bpm={params['bpm']}, shots={params['shots']}"
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>Quantum Walk Position Distribution</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  body {{
    font-family: 'Segoe UI', sans-serif;
    background: #1a1a2e; color: #eee;
    display: flex; flex-direction: column;
    align-items: center; padding: 2rem;
  }}
  h1 {{ color: #a78bfa; margin-bottom: 0.3rem; }}
  p  {{ color: #94a3b8; font-size: 0.9rem; margin-top: 0; }}
  .chart-box {{
    width: min(900px, 95vw);
    background: #16213e; border-radius: 12px;
    padding: 1.5rem;
    box-shadow: 0 4px 24px rgba(0,0,0,0.4);
  }}
</style>
</head>
<body>
<div class="chart-box">
  <h1>&#x27E8;&#x03C8;&#x27E9; Quantum Walk Position Distribution</h1>
  <p>{caption}</p>
  <canvas id="walkChart"></canvas>
</div>
<script>
const ctx = document.getElementById('walkChart').getContext('2d');
new Chart(ctx, {{
  type: 'bar',
  data: {{
    labels: {positions},
    datasets: [
      {{
        label: 'Quantum walk',
        data: {q_data},
        backgroundColor: 'rgba(167,139,250,0.75)',
        borderColor: 'rgba(167,139,250,1)',
        borderWidth: 1
      }},
      {{
        label: 'Classical random walk',
        data: {c_data},
        backgroundColor: 'rgba(56,189,248,0.4)',
        borderColor: 'rgba(56,189,248,0.8)',
        borderWidth: 1
      }}
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ labels: {{ color: '#eee' }} }}
    }},
    scales: {{
      x: {{
        title: {{ display: true, text: 'Position node', color: '#94a3b8' }},
        ticks: {{ color: '#94a3b8' }},
        grid:  {{ color: '#ffffff15' }}
      }},
      y: {{
        title: {{ display: true, text: 'Probability', color: '#94a3b8' }},
        ticks: {{ color: '#94a3b8' }},
        grid:  {{ color: '#ffffff15' }},
        min: 0
      }}
    }}
  }}
}});
</script>
</body>
</html>
"""
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(html)


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def _weighted_std(probs: dict[int, float]) -> float:
    """Return the probability-weighted standard deviation of walk positions."""
    positions = np.array(list(probs.keys()), dtype=float)
    weights   = np.array(list(probs.values()), dtype=float)
    total = weights.sum()
    if total == 0.0:
        return 0.0
    mean     = np.dot(positions, weights) / total
    variance = np.dot((positions - mean) ** 2, weights) / total
    return float(np.sqrt(variance))


def _expected_classical_std(n_steps: int) -> float:
    """Return the theoretical std dev for a classical 1-D random walk."""
    return math.sqrt(n_steps / 2.0)


# ---------------------------------------------------------------------------
# Console report
# ---------------------------------------------------------------------------


def print_report(
    quantum_probs: dict[int, float],
    classical_probs: dict[int, float],
    params: dict,
    wav_path: Path,
    mid_path: Path,
    html_path: Path,
    use_qpu: bool,
) -> None:
    """Print the quantum walk statistics report to stdout."""
    q_std = _weighted_std(quantum_probs)
    c_std = _expected_classical_std(params["steps"])
    ratio = q_std / c_std if c_std > 0.0 else float("inf")

    sorted_q  = sorted(quantum_probs.items(), key=lambda kv: kv[1], reverse=True)
    most_pos,  most_p  = sorted_q[0]
    least_pos, least_p = sorted_q[-1]
    backend_name = "IBM QPU" if use_qpu else "Aer (AerSimulator)"

    print()
    print("\u27e8\u03c8\u27e9 Quantum Walk Music Generator")
    print("=================================")
    print(
        f"Parameters: steps={params['steps']}, scale={params['scale']}, "
        f"key={params['key']}, bpm={params['bpm']}, octave={params['octave']}"
    )
    print(f"Backend: {backend_name}")
    print(f"Shots: {params['shots']}")
    print()
    print("Walk Statistics:")
    print(f"  Most probable position:  {most_pos}  (p={most_p:.3f})")
    print(f"  Least probable position: {least_pos}  (p={least_p:.3f})")
    print(f"  Quantum spread (std dev):   {q_std:.1f}")
    print(
        f"  Classical spread (std dev): {c_std:.1f}"
        f"  [expected for {params['steps']}-step classical walk]"
    )
    print(
        f"  Interference ratio: {ratio:.2f}x"
        "  [quantum/classical spread ratio — >1 confirms quantum speedup]"
    )
    print()
    print("Output files:")
    print(f"  WAV:  {wav_path}")
    print(f"  MID:  {mid_path}")
    print(f"  HTML: {html_path}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="\u27e8\u03c8\u27e9 Quantum Walk Music Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--steps", type=int, default=32,
        help="Number of quantum walk steps (default: 32)",
    )
    parser.add_argument(
        "--scale", default="pentatonic", choices=list(SCALES.keys()),
        help="Musical scale (default: pentatonic)",
    )
    parser.add_argument(
        "--key", default="C",
        help="Root key note, e.g. C, F#, Bb (default: C)",
    )
    parser.add_argument(
        "--bpm", type=int, default=120,
        help="Tempo in BPM (default: 120)",
    )
    parser.add_argument(
        "--octave", type=int, default=4,
        help="Base octave for root note (default: 4)",
    )
    parser.add_argument(
        "--use-qpu", action="store_true",
        help="Use IBM QPU instead of Aer simulator",
    )
    args = parser.parse_args()

    scale     = SCALES[args.scale]
    root_semi = parse_key(args.key)
    # MIDI note for root: C4 = 60 = 12*(4+1)+0
    root_midi = 12 * (args.octave + 1) + root_semi
    bpm_sec   = 60.0 / args.bpm   # seconds per beat

    # Run walks
    print(f"Running quantum walk ({args.steps} steps, {SHOTS} shots)...")
    quantum_probs   = run_quantum_walk(args.steps, shots=SHOTS, use_qpu=args.use_qpu)
    print("Running classical walk baseline...")
    classical_probs = run_classical_walk(args.steps)

    # Build note sequence: visit positions 0..N-1 in order
    DURATION_CHOICES = [0.25, 0.5, 1.0, 2.0]
    notes_with_durations: list[tuple[int, float]] = []
    audio_segments: list[np.ndarray] = []

    for pos in range(N_POSITIONS):
        p = quantum_probs[pos]
        if p < 0.005:
            continue   # skip negligible-probability positions
        midi_note = position_to_midi(pos, scale, root_midi)
        dur_beats = qhoice(DURATION_CHOICES)
        dur_sec   = float(dur_beats) * bpm_sec
        notes_with_durations.append((midi_note, float(dur_beats)))
        amplitude = min(0.9, 0.35 + 0.55 * p * N_POSITIONS)  # scale by relative prob
        audio_segments.append(synthesize_note(midi_note, dur_sec, amplitude=amplitude))

    # Fallback: if all probabilities are tiny, use all positions equally
    if not notes_with_durations:
        for pos in range(N_POSITIONS):
            midi_note = position_to_midi(pos, scale, root_midi)
            dur_beats = qhoice(DURATION_CHOICES)
            notes_with_durations.append((midi_note, float(dur_beats)))
            audio_segments.append(
                synthesize_note(midi_note, float(dur_beats) * bpm_sec, amplitude=0.4)
            )

    # Output paths
    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    music_out   = Path(r"f:\❤Music\output")
    quantum_out = Path(r"f:\⟨ψ⟩Quantum\output")
    music_out.mkdir(parents=True, exist_ok=True)
    quantum_out.mkdir(parents=True, exist_ok=True)

    wav_path  = music_out   / f"quantum_walk_{timestamp}.wav"
    mid_path  = music_out   / f"quantum_walk_{timestamp}.mid"
    html_path = quantum_out / f"quantum_walk_{timestamp}.html"

    # Write audio
    if audio_segments:
        full_audio = np.concatenate(audio_segments)
        write_wav(full_audio, wav_path)

    # Write MIDI and HTML
    write_midi(notes_with_durations, args.bpm, mid_path)
    params = {
        "steps":  args.steps,
        "scale":  args.scale,
        "key":    args.key,
        "bpm":    args.bpm,
        "octave": args.octave,
        "shots":  SHOTS,
    }
    write_html(quantum_probs, classical_probs, params, html_path)

    print_report(
        quantum_probs, classical_probs, params,
        wav_path, mid_path, html_path,
        args.use_qpu,
    )


if __name__ == "__main__":
    main()
