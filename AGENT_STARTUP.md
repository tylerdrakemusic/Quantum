# ⚡ AGENT STARTUP DIRECTIVE — ⟨ψ⟩Quantum

**READ THIS FIRST.** Context bootstrap for any AI agent picking up work on the ⟨ψ⟩Quantum project.

---

## 1. Gather Context

```
1. Read this file completely
2. Read research/algorithm_roadmap.md for provider and algorithm context
3. Read README.md for architecture context if needed
4. Read the active FR with f:\⊕Workspace\src\utils\fr_cli.py before acting
```

## 2. Project Location & Key Paths

| Resource | Path |
|----------|------|
| **Project Root** | repository root (`f:\⟨ψ⟩Quantum\` in the main checkout) |
| **Workspace Root** | `f:\⊕Workspace\` |
| **FR Registry** | `f:\⊕Workspace\src\data\fr_ledgers.db`, accessed through `fr_cli.py` |
| **Python Executable** | `C:\G\python.exe` |
| **Agent Definitions** | `.github/agents/⟨ψ⟩quantum-*.agent.md` |
| **Instructions** | `.github/instructions/⟨ψ⟩quantum-*.instructions.md` |
| **Execution Policy** | `src/config/execution_policy.json` |

### ⟨ψ⟩Quantum Agents (`.github/agents/`)

All ⟨ψ⟩Quantum agents are prefixed `⟨ψ⟩quantum-` and live at `.github/agents/⟨ψ⟩quantum-*.agent.md`. **Scan that glob to discover available agents.**

| Agent | Purpose |
|-------|---------|
| **⟨ψ⟩quantum-orchestrator** | Top-level coordinator. Decomposes requests, delegates, synthesizes. Default entry point. |
| **⟨ψ⟩quantum-research** | Quantum computing literature, algorithm exploration, use-case discovery |
| **⊕workspace-hygiene** | Unified workspace hygiene — archive done tasks, prune stale files, agent infrastructure audit |

> **Adding agents:** Create `.github/agents/⟨ψ⟩quantum-<name>.agent.md` with a keyword-rich `description` in frontmatter.

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
- **Cache filler:** `QuantumCacheFill_Monthly`, day 1 at 07:00 UTC
- **Shor's benchmark:** `ShorsMonthlyBench`, day 1 at 08:00 UTC
- **VQE benchmark:** `VQEMonthlyBench`, day 15 at 03:00 UTC
- **Daily monitors:** `QuantumCacheDepletionGuard_Daily` at 06:00 UTC, `PolicyComplianceAudit_Daily` at 07:00 UTC, and `QuantumBackendAvailabilityMonitor_Daily` at 08:00 UTC
- **Source of truth:** `src/config/execution_policy.json` (scripts/docs must read this schedule)

### Backward Compatibility
The package-facing API is under `src/quantum_toolkit/`. The compatibility module
`src/quantum_rt.py` re-exports the public random functions for existing imports.

## 4. Key Data

| Asset | Path | Notes |
|-------|------|-------|
| Quantum bitstring cache | `src/data/liveCache/ty_string_cache.txt` | Configured/runtime location; ignored and may be absent in a clean checkout |
| Cache backups | `qbackups/` | Root-level, ignored, operator-managed timestamped snapshots before each refill |
| Cache verification | `C:\G\python.exe tools\verify_cache.py` | Read-only integrity check |
| Cache fallback | `secrets` CSPRNG | Used when the configured cache is absent, rejected, or exhausted; verification reports unavailable when absent |
| Shor's V2 perf data | `research/shors_v2_performance.tsv` | Factorization benchmarks |

## 5. Safety and Collaboration

- IBM credentials are the `IBM_CLOUD_API_KEY` and `IBM_QUANTUM_INSTANCE`
  environment variables. Never log, expose, or hardcode them.
- Never delete or truncate the live cache without a backup. `tools/fill_cache.py`
  creates a timestamped backup before replacement.
- Never run a cache fill while another fill is active. Respect the 10-minute
  monthly IBM Quantum quota.
- Each FR uses one branch and one worktree per repository. Use the shared
  `feature/<FR-ID>`, `fix/<FR-ID>`, or `chore/<FR-ID>` naming convention,
  route branch operations through `⊕workspace-ci`, and never push directly to
  `main`.
- Before acting, read the FR with `C:\G\python.exe f:\⊕Workspace\src\utils\fr_cli.py get <FR-ID>`.
- After acting, record one FR event with `fr_cli.py record-event`.
