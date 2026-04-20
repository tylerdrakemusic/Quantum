# ⟨ψ⟩Quantum — Quantum Computing Toolkit

Tyler James Drake's quantum computing project. Provides quantum random number generation, IBM Quantum backend management, algorithm research, and a cache of true quantum random bits for use across projects.

## Architecture

```
⟨ψ⟩Quantum/
├── src/
│   ├── core/
│   │   ├── quantum_rt.py        # Quantum random library (qRandom, qhoice, quuffle, etc.)
│   │   ├── quantum_backend.py   # IBM Quantum + Aer backend manager (champion-challenger)
│   │   ├── quantum_t.py         # Quantum text/creative utilities
│   │   ├── qaoa.py              # QAOA solver (QAOASolver + QAOASolverQPU, MaxCut, scheduling)
│   │   └── __init__.py
│   ├── data/
│   │   ├── ty_string_cache.txt  # Live quantum bitstring cache
│   │   └── qbackups/            # Timestamped cache backups
│   └── utils/
│       └── __init__.py
├── tools/
│   └── fill_cache.py            # Monthly quota filler (IBM 10-min/month)
├── research/
│   ├── shors.py                 # Shor's algorithm — integer factorization via QPE
│   ├── shors_v2.py              # Shor's V2 — enhanced with concurrency & OOP
│   ├── shors_v2_performance.tsv # Factorization benchmark results
│   ├── dicksons.py              # Dixon's algorithm — smooth number factorization
│   ├── grover_experiment.py     # Grover's search algorithm experiment
│   ├── quantum_qkd_bb84.py      # BB84 Quantum Key Distribution protocol
│   └── algorithm_roadmap.md     # Provider strategy + next algorithms
├── docs/                        # Documentation
│   └── archive/completed_tasks.md
├── AGENT_STARTUP.md             # Agent context bootstrap
├── PROJECT_PROFILE.json         # Project configuration
├── TODO_AI.md                   # Agent task queue
├── TODO_TYLER.md                # Human action items
└── README.md
```

### QAOA Integration Adapters

Domain-specific QAOA adapters live in their domain-owner projects and import from this core:

| File | Lives In | Imports From Here |
|------|----------|-------------------|
| `setlist_optimizer.py` | `❤Music/src/integrations/` | `core.qaoa` via sys.path bridge |
| `supplement_scheduler.py` | `∞Life/src/integrations/` | `core.qaoa` via sys.path bridge |

## Quick Start

```python
# From any project:
import sys
sys.path.insert(0, "f:/executedcode/⟨ψ⟩Quantum/src")
from core.quantum_rt import qRandom, qRax, qhoice, quuffle, qsample, qpermute, qRandomBool, qRandomBitstring
```

## API Reference

| Function | Description |
|----------|-------------|
| `qRandom(n)` | Random integer 0..n using quantum bits |
| `qRax(min, max)` | Random integer in [min, max] |
| `qhoice(lst)` | Random selection from list |
| `quuffle(lst)` | In-place quantum shuffle (Fisher-Yates) |
| `qsample(lst, k)` | Sample k items without replacement |
| `qpermute(lst)` | Return a shuffled copy |
| `qRandomBool()` | Random True/False |
| `qRandomBitstring(n)` | n random bits from cache (classical fallback) |
| `generate_random_bitstring(n)` | Generate bits directly from IBM quantum processor |

## Data Pipeline

- **IBM Quantum** → `fill_cache.py` → `ty_string_cache.txt` → consumed by `qRandomBitstring()`
- Monthly scheduled task: `QuantumCacheFill_Monthly` (1st of month, 2:00 AM)
- 10-minute monthly quota on IBM Quantum (free tier)
- Backend: `ibm_fez` (156-qubit Eagle processor)
- Falls back to classical random when cache is depleted

## Consumers

These scripts in `executedcode/` import from `quantum_rt`:
- `$$!!cleanUpDirSizes.py`
- `$$~~$$tyja.py`
- `$$~~$$TycloneBackup.py`
- `$$~~TyClone$$.py`
- `.py` (bookshelf manager)
- `Open Spotify.py`
- `quantum_sampler.py`
- `QuantumNoiseGate.py`
- `quantumLifeEnhancer.py`

## Future Use Cases

- Quantum key distribution (BB84 — prototype exists)
- Quantum noise gate signal processing
- Quantum-enhanced optimization (QAOA, VQE)
- Quantum machine learning (QML classifiers)
- True random number generation for cryptographic applications
