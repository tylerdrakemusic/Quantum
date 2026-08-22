# FR-20260821 Calibration-Source Feasibility Repair Proof

Date: 2026-08-22

## Change-specific checks

- The strengthened contract test first failed on the missing explicit Aer
  mapping label, then passed after the documentation-only repair.
- Focused command: `C:\G\python.exe -m pytest tests/test_ibm_fez_calibration_source_feasibility.py -q`
- Result: `1 passed`
- `git diff --check`: passed

## Contract coverage

The focused test now asserts the seven provenance fields, the 24-hour fresh
and aging boundary, the 7-day aging and stale boundary, undated handling,
supported/approximate/unsupported Aer mapping labels, and the explicit
benchmark-preservation boundary.

The repair changes only the research note, its focused contract test, and this
proof artifact. Benchmark behavior, scheduling, provider calls, execution
policy, dependencies, schema, and unrelated topology coverage are unchanged.