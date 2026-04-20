# ⟨ψ⟩Quantum Algorithm Roadmap
*Generated 2026-04-15 — champion-challenger evaluation*

## Provider Strategy: Champion-Challenger (Free Tier Only)

| Role | Provider | Access | True QR? | Cost |
|------|----------|--------|----------|------|
| **Champion** | IBM Quantum (Open Plan) | 10 min/month, `ibm_fez` 156q | YES | $0 |
| **Challenger 1** | Qiskit Aer (local) | Unlimited | NO (pseudorandom) | $0 |
| **Challenger 2** | Amazon Braket (monitor) | Sim-only free; QPU ~$2/fill | YES (if paid) | $0 now |

**Verdict:** IBM Quantum is the *only* free-tier provider with real quantum hardware.
No other vendor offers free QPU access as of 2026-04. Aer covers unlimited local simulation.

## Next Algorithms (Priority Order)

| # | Algorithm | Platform | Hours | Project Tie-in | Status |
|---|-----------|----------|-------|----------------|--------|
| 1 | **QAOA** (combinatorial optimization) | Aer + QPU | 6-10 | ❤Music setlists, ∞Life supplement timing | ✅ Implemented |
| 2 | **VQE** (molecular simulation) | Aer + QPU | 8-12 | ∞Life molecular interactions | ❌ Not started |
| 3 | **Quantum Walk Music Generator** | Aer + QPU | 8-12 | ❤Music melody/chord generation | ❌ Not started |
| 4 | **Quantum Kernel SVM** | Aer | 6-8 | ∞Life biomarker classification | ❌ Not started |
| 5 | **QEC Codes** (error correction) | Aer | 10-15 | Foundational knowledge | ❌ Not started |

## Key Dependencies to Install

```
qiskit-aer          ✅ installed
qiskit-nature       ❌ needed for VQE (#2)
pyscf               ❌ needed for VQE (#2)
qiskit-machine-learning  ❌ needed for QML (#4)
midiutil            ❌ needed for Quantum Walk Music (#3)
```
