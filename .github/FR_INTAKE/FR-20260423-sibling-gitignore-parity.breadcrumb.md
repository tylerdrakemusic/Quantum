# Intake Breadcrumb — FR-20260423-sibling-gitignore-parity (⟨ψ⟩Quantum slice)

This file is a placeholder commit so a draft PR can be opened at the BRANCHED
state. The implementing agent (overseer) will remove or supersede this file
when landing the actual work.

- **FR ID:** FR-20260423-sibling-gitignore-parity
- **Project slice:** ⟨ψ⟩Quantum
- **Type:** chore
- **Ledger (lives in ⊕Workspace):** `.github/FR_LEDGERS/FR-20260423-sibling-gitignore-parity.md`
- **Cycle timer:** 6b55a663-313c-45a2-a44f-d0df0da33e48
- **Branched at:** 2026-04-23
- **Owner (at branch time):** ⊕workspace-ci (delegated by ⊕workspace-intake)

### Scope for this repo
- `.gitignore` covers `__pycache__/`, `*.pyc`, `src/data/*.db`, `src/data/backups/` (skip patterns not used here)
- Untrack any currently-tracked `.pyc` / binary DB with `git rm --cached`
- `src/data/schema.sql` sanitized SQLCipher dump committed IF repo has a SQLCipher DB (implementer to verify)
- `git status --short` clean after landing

See ⊕Workspace ledger for full acceptance criteria and event log.
