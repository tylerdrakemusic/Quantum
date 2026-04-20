# ⚡ AGENT STARTUP DIRECTIVE — ⟨ψ⟩Quantum

**READ THIS FIRST.** Context bootstrap for any AI agent picking up work on the ⟨ψ⟩Quantum project.

---

## 1. Gather Context

```
1. Read this file completely
2. Read TODO_AI.md for current agentic task queue
3. Read TODO_TYLER.md for pending human actions and blockers
4. Read PROJECT_PROFILE.json for current project state
5. Read README.md for architecture context if needed
```

## 2. Project Location & Key Paths

| Resource | Path |
|----------|------|
| **Project Root** | `f:\executedcode\⟨ψ⟩Quantum\` |
| **Workspace Root** | `f:\` |
| **Parent Repo** | `f:\executedcode\` (private git repo — source controlled) |
| **Python Executable** | `C:\G\python.exe` |
| **Agent Definitions** | `f:\.github\agents\⟨ψ⟩quantum-*.agent.md` |
| **Instructions** | `f:\.github\instructions\⟨ψ⟩quantum-*.instructions.md` |
| **System Specs** | `f:\SYSTEM_SPECS.md` |

### ⟨ψ⟩Quantum Agents (`f:\.github\agents\`)

All ⟨ψ⟩Quantum agents are prefixed `⟨ψ⟩quantum-` and live at `f:\.github\agents\⟨ψ⟩quantum-*.agent.md`. **Scan that glob to discover available agents.**

| Agent | Purpose |
|-------|---------|
| **⟨ψ⟩quantum-orchestrator** | Top-level coordinator. Decomposes requests, delegates, synthesizes. Default entry point. |
| **⟨ψ⟩quantum-research** | Quantum computing literature, algorithm exploration, use-case discovery |
| **⟨ψ⟩quantum-hygiene** | Project cleanup — archive done tasks, prune stale files |

> **Adding agents:** Create `f:\.github\agents\⟨ψ⟩quantum-<name>.agent.md` with a keyword-rich `description` in frontmatter.

## 3. Project Summary

**⟨ψ⟩Quantum** is Tyler James Drake's quantum computing toolkit. It provides:
- **Quantum random library** (`quantum_rt.py`) — cache-based true quantum randomness with classical fallback
- **IBM Quantum backend manager** (`quantum_backend.py`) — least-busy backend selection for IBM Quantum Platform
- **Bitstring cache pipeline** — monthly automated refill via IBM's free 10-min quota
- **Algorithm implementations** — Shor's factorization, Dixon's factorization, Grover's search, QKD BB84

### IBM Quantum Access
- **Tier:** Free (10 minutes/month)
- **Primary backend:** `ibm_fez` (156-qubit Eagle processor)
- **Shots per circuit:** 4096
- **Cache filler:** Scheduled task `QuantumCacheFill_Monthly` runs 1st of each month at 2AM

### Backward Compatibility
Consumer scripts in `f:\executedcode\` still import via `from quantum_rt import qhoice` etc. Thin shim files at `f:\executedcode\quantum_rt.py` and `f:\executedcode\quantum_backend.py` redirect to `⟨ψ⟩Quantum/src/core/`.

## 4. Key Data

| Asset | Path | Notes |
|-------|------|-------|
| Quantum bitstring cache | `src/data/ty_string_cache.txt` | ~1M+ bits, symlinked from `executedcode/` |
| Cache backups | `src/data/qbackups/` | Timestamped snapshots before each refill |
| Shor's V2 perf data | `research/shors_v2_performance.tsv` | Factorization benchmarks |

## 5. Current State (2026-04-17)

- **Phase 0 complete** — project extracted, shims in place, cache operational
- **Phase 1 complete** — champion-challenger architecture, ProviderTier enum, Qiskit Aer integrated
- **Phase 2 QAOA complete** — `QAOASolver` + `QAOASolverQPU` in `src/core/qaoa.py`
  - Integration adapters moved to domain-owner projects per scope rules:
    - `setlist_optimizer.py` → `❤Music/src/integrations/` (data owner: ❤Music)
    - `supplement_scheduler.py` → `∞Life/src/integrations/` (data owner: ∞Life)
  - Both adapters import `core.qaoa` via `sys.path` bridge
- **Phase 2 pending** — VQE, quantum walk music gen, quantum kernel SVM, QEC, Aer noise models
- Cache at 1M+ quantum bits; monthly fill on schedule (1st of month, 2AM)
- symlink N/A on exFAT — path resolution works directly
