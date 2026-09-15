# Time-Crystal Dynamics Capability Specification

## Summary

This document specifies a future, isolated capability for studying discrete
time-crystal (DTC) dynamics in the Quantum project. The capability would
describe a periodically driven many-body experiment, analyze measured or
simulated response, and preserve enough provenance to distinguish a robust
subharmonic response from finite-size beating, preparation error, heating,
noise, or an analysis artifact.

This is a research and design artifact only. It does not implement a runtime
API, add a dependency, change a schema, create a dashboard, submit an IBM
Quantum job, or modify the randomness, cache, or benchmark pipelines. A strong
simulation result would be evidence that the selected model and analysis are
internally consistent, not evidence of quantum advantage.

## Capability Boundary

The proposed capability is `time_crystal_dynamics`, owned by the Quantum
project and deliberately separate from:

- the quantum-randomness and live-cache systems, which have a distinct
  production provenance and quota contract;
- the benchmark families, which compare algorithm-specific scalar metrics and
  replay outcomes;
- the generic IBM backend manager, which must not acquire experiment-specific
  control policy as a side effect; and
- any dashboard implementation, which should consume an approved evidence
  representation rather than define scientific validity.

The boundary is an analysis and experiment-description layer. It may later
consume a local simulator result, an Aer-style noisy simulation result, or an
operator-approved hardware result. It must never silently promote one source
of evidence into another. In particular, an ideal statevector trace is not a
hardware observation, and a hardware observation is not a claim of quantum
advantage.

### Explicit non-goals

- No production execution path or automatic hardware submission.
- No use of the live randomness cache for seeds, drive phases, or analysis
  decisions.
- No reuse of benchmark tables or composite benchmark scores.
- No schema migration or dependency addition in this FR.
- No claim that observing period doubling proves a thermodynamic time crystal.
- No claim of quantum advantage, computational speedup, or fault tolerance.
- No material claim based on one finite-size trace, one seed, or one device
  calibration snapshot.

## Scientific Model

The initial model should be a periodically driven spin chain, such as a
finite Ising chain with a near-pi pulse followed by an interaction and
disorder-preserving or disorder-perturbing evolution. The exact Hamiltonian
and Floquet unitary must be frozen in the experiment record. The primary
observable is a local or collective magnetization measured stroboscopically
after each drive period:

$$
M(n) = \frac{1}{L}\sum_{j=1}^{L} \langle Z_j(nT) \rangle,
\qquad
\omega_d = \frac{2\pi}{T}.
$$

A DTC candidate has a response near half the drive frequency, equivalently a
sign-alternating response with period $2T$:

$$
\omega_* \approx \frac{\omega_d}{2},
\qquad
M(n+1) \approx -M(n).
$$

This signature is necessary but not sufficient. A valid interpretation also
requires persistence over a declared observation window, stability under
allowed perturbations, and rejection of simpler explanations such as a
coherent two-cycle oscillation in a small isolated system.

The specification should support both a discrete-time response and a spectral
view. The spectral estimate must record its windowing, detrending, frequency
grid, resolution, and uncertainty method. A peak at $\omega_d/2$ without
those details is not a reproducible claim.

## Conceptual Typed Contract

The following is a non-executable type sketch. It defines the future contract;
it is not an instruction to implement these types in this FR.

```text
enum SourceKind:
    local_ideal_simulation
    aer_noisy_simulation
    ibm_hardware_observation

enum ValidityStatus:
    candidate
    supported
    inconclusive
    invalid
    unavailable

enum FailureMode:
    malformed_protocol
    insufficient_time_window
    insufficient_system_size
    nonstationary_drive
    thermal_or_heating_drift
    finite_size_beating
    noise_dominated
    calibration_or_readout_limited
    spectral_resolution_limited
    perturbation_test_failed
    robustness_not_tested
    provenance_incomplete
    hardware_not_authorized

type DriveProtocol = {
    model_family: string,
    system_size: int,
    drive_period: float,
    pulse_sequence: list[PulseStep],
    interaction_parameters: map[string, float],
    disorder_parameters: map[string, float],
    observable: ObservableSpec,
    periods: int,
    repetitions: int,
    measurement_schedule: string,
}

type DynamicsInput = {
    protocol: DriveProtocol,
    source: SourceKind,
    seed: int | null,
    noise_model: NoiseModel | null,
    perturbation_sweeps: list[PerturbationSpec],
    baseline_reference: string | null,
    authorization: "design_only" | "local_only" | "operator_approved_hardware",
}

type Provenance = {
    capability_version: string,
    experiment_id: string,
    source: SourceKind,
    simulator_or_backend: string,
    software_revision: string,
    protocol_digest: string,
    seed: int | null,
    noise_model_digest: string | null,
    calibration_reference: string | null,
    evidence_references: list[string],
    created_at: string,
}

type DynamicsOutput = {
    status: ValidityStatus,
    response_trace: TraceSummary,
    spectral_summary: SpectralSummary,
    robustness: list[RobustnessResult],
    lifetime_and_scaling: list[ScalingResult],
    failure_modes: list[FailureMode],
    scientific_claims: list[string],
    provenance: Provenance,
}
```

### Contract rules

1. `source`, protocol digest, seed policy, and noise/calibration metadata are
   required provenance. Unknown values are represented as unavailable, never
   guessed.
2. `supported` means that the declared tests passed within declared
   tolerances. It does not mean "time crystal proven" or "quantum advantage".
3. `candidate` is an analysis result that has a subharmonic signal but lacks
   one or more robustness, scaling, or false-positive controls.
4. `inconclusive` is the correct result for insufficient resolution, ambiguous
   lifetime, missing perturbation controls, or conflicting diagnostics.
5. `invalid` is reserved for malformed input, violated protocol assumptions,
   impossible metadata, or evidence that directly fails a required validity
   gate.
6. `unavailable` is used when the requested source cannot be run or its
   evidence cannot be read. It must not be converted into a failed scientific
   result.

## Backend and Control Architecture

### Local ideal simulation

The first implementation stage should be a deterministic local reference
model. It should generate the Floquet protocol, collect stroboscopic
observables, and emit an immutable evidence bundle in memory or as a research
artifact. It should support seed replay and small system-size sweeps. This
stage is useful for checking the analysis math, not for claiming physical
realism.

### Future Aer-style simulation

A later adapter may translate the frozen protocol into Qiskit Aer circuits or
an equivalent simulator. The adapter should own circuit translation and noise
configuration, while the capability layer owns validation and provenance.
Noise configurations should include at least depolarizing/readout noise,
coherent over-rotation, and a heating or leakage proxy where the simulator
supports one. Each noise model must be identified by a digest and versioned
configuration. Ideal and noisy results should be compared side by side, never
combined into one score.

### Future IBM control/backend path

Hardware support should be an explicit adapter with these stages:

1. Validate an operator-approved protocol and authorization record.
2. Compile and inspect the pulse/circuit representation without submission.
3. Record backend identity, coupling/layout choices, shots, transpiler
   settings, and calibration reference.
4. Submit only through the existing governed backend path after a separate
   approval decision and quota check.
5. Capture readout counts and operational metadata with credentials redacted.
6. Feed the resulting evidence into the same analysis contract with
   `source=ibm_hardware_observation`.

This FR must stop before stage 4. The existing free-tier budget is too small
for broad system-size, disorder, perturbation, and lifetime sweeps. Current
IBM noisy devices also make long Floquet sequences vulnerable to gate error,
readout error, drift, leakage, and heating. A short hardware trace could be a
calibration or control demonstration, but it would not establish a DTC phase.

## Scientific Validity Tests

The future validator should report each gate independently, with its
configuration and outcome. It should not collapse them into a single score.

### 1. Subharmonic response

- Estimate the alternating component from the stroboscopic trace and report
  amplitude, confidence interval, and baseline-corrected signal.
- Locate the dominant spectral component with a declared window and frequency
  resolution. Require consistency with $\omega_d/2$ within a predeclared
  tolerance, not merely the largest nearby FFT bin.
- Compare against a phase-randomized or shuffled-trace null model and report
  the false-discovery procedure across all tested parameter points.
- Require the response to remain visible beyond the initial transient window.

### 2. Robustness

Repeat the analysis over a declared neighborhood of drive imperfections,
interaction strengths, disorder realizations, initial states, and random seeds.
The candidate should survive perturbations that are physically meaningful for
the model, rather than only perturbations selected after viewing the trace.
The report must distinguish robustness of a finite experiment from proof of a
phase in the thermodynamic limit.

### 3. Lifetime and scaling

Measure the envelope of the subharmonic component over time and report the
chosen lifetime model. Fit uncertainty and goodness-of-fit must be shown; an
arbitrary cutoff is insufficient. Repeat over increasing system sizes and
longer windows where possible. A lifetime that does not improve, or that is
consistent with a finite-size revival, should remain `inconclusive`.

### 4. Perturbations and controls

Include controls that remove or alter the proposed mechanism: no-disorder,
no-interaction, pulse-angle detuning, phase-randomized drive, and a matched
classical or noninteracting reference where meaningful. The analysis should
test whether the signal follows the drive, whether it survives perturbations,
and whether it disappears under a control expected to destroy it.

### 5. False-positive rejection

The validator must actively check for:

- a two-cycle initial state that trivially produces period doubling;
- beating between nearby quasienergies in a finite chain;
- aliasing or a frequency-grid artifact;
- transient synchronization before heating destroys the response;
- readout alternation or calibration drift;
- post-selection or parameter selection on the same trace used for inference;
- a classical driven oscillator reproducing the same trace; and
- an analysis result caused by insufficient sampling or window choice.

Failure of any required control should produce `inconclusive` or `invalid`,
not a weaker form of `supported`.

## Dashboard Plan

No dashboard is implemented by this FR. A future dashboard should be a
read-only evidence viewer with an explicit source and validity banner.

### Primary view

- **Protocol header:** experiment ID, source kind, model, system size, drive
  period, periods measured, seed policy, and provenance status.
- **Pulse timeline:** horizontal timeline of drive periods and pulse steps,
  with interaction and measurement markers. Show the declared protocol, not
  inferred timing.
- **Response trace:** stroboscopic observable versus period, with alternating
  sign or phase coloring, transient window shading, uncertainty bands, and
  heating/lifetime envelope.
- **Spectral evidence:** frequency-response plot with the drive frequency and
  half-frequency markers, window metadata, resolution, null comparison, and
  confidence information.
- **Robustness comparison:** small multiples or an aligned table for pulse
  detuning, disorder, interaction, initial state, noise model, and system
  size. Each panel must preserve its own source and configuration.

### State presentation

The top-level state must be one of `candidate`, `supported`, `inconclusive`,
`invalid`, or `unavailable`, with a concise reason and expandable failed
gates. The UI must never use a green success treatment for an `inconclusive`
trace, and it must not imply hardware evidence when the source is simulation.
Missing provenance, unrun controls, and unmeasured scaling should be visible
as missing evidence rather than silently omitted.

## IBM Feasibility and Staging

| Stage | Evidence source | Purpose | Exit condition |
| --- | --- | --- | --- |
| 0 | Design only | Freeze contract, controls, and claims vocabulary | Review accepts boundaries |
| 1 | Local ideal model | Validate trace and spectral analysis | Reproducible seeded fixtures |
| 2 | Local noisy/Aer-style model | Stress noise, heating proxies, and false positives | Controls reject known artifacts |
| 3 | Read-only hardware compilation | Estimate depth, measurement cost, and layout | Operator reviews feasibility |
| 4 | Approved hardware pilot | Collect a narrowly scoped observation | Separate FR authorizes submission |
| 5 | Comparative study | Repeat sizes, perturbations, and controls | Evidence supports or rejects claim |

The current free IBM tier is suitable, at most, for a later small pilot after
stages 0-3. It is not suitable for the statistical and scaling burden of a
strong DTC claim. A pilot should be described as a noisy control experiment
and should be allowed to end as `inconclusive`. No hardware job is authorized
by this document.

## Failure and Safety Rules

- Refuse to analyze a trace whose protocol digest or source metadata is
  missing.
- Preserve partial evidence with an explicit failure mode; do not fabricate
  missing calibration, noise, or lifetime values.
- Keep hardware authorization separate from scientific validity.
- Keep all results outside the existing benchmark and randomness stores until
  a future schema and retention decision is approved.
- Treat a parser, simulator, or plotting failure as an execution failure, not
  as evidence against time-crystal behavior.
- Treat a successful ideal simulation as model validation only.

## References

1. D. V. Else, B. Bauer, and C. Nayak, "Floquet Time Crystals," *Physical
   Review Letters* 117, 090402 (2016), DOI: 10.1103/PhysRevLett.117.090402,
   https://doi.org/10.1103/PhysRevLett.117.090402
2. V. Khemani, A. Lazarides, R. Moessner, and S. L. Sondhi, "Phase Structure
   of Driven Quantum Systems," *Physical Review Letters* 116, 250401 (2016),
   DOI: 10.1103/PhysRevLett.116.250401,
   https://doi.org/10.1103/PhysRevLett.116.250401
3. J. Zhang et al., "Observation of a Discrete Time Crystal," *Nature* 543,
   217-220 (2017), DOI: 10.1038/nature21413,
   https://doi.org/10.1038/nature21413
4. S. Choi et al., "Observation of Discrete Time-Crystalline Order in a
   Disordered Dipolar Many-Body System," *Nature* 543, 221-225 (2017),
   DOI: 10.1038/nature21426,
   https://doi.org/10.1038/nature21426
5. J. Randall et al., "Many-body-localized Discrete Time Crystal with a
   Realistic Hamiltonian," *Science* 374, 1474-1478 (2021),
   DOI: 10.1126/science.abk2397,
   https://doi.org/10.1126/science.abk2397
6. M. P. Zaletel et al., "Colloquium: Floquet time crystals," *Reviews of
   Modern Physics* 95, 031001 (2023), DOI: 10.1103/RevModPhys.95.031001,
   https://doi.org/10.1103/RevModPhys.95.031001
7. IBM Quantum Documentation, "Qiskit Aer simulator and noise models,"
   https://qiskit.github.io/qiskit-aer/
8. Quantum project, `docs/benchmark-provenance.md`, for the existing policy
   that evidence, replay, unavailable metadata, and scientific claims remain
   explicit and non-composite.

## Implementation Handoff

This specification is ready for a future, separately approved implementation
FR. That FR should begin with contract tests over synthetic fixtures and a
read-only local reference model. It should not add IBM submission behavior,
schema changes, dashboard code, or dependencies until the staged feasibility
and authorization reviews are complete.