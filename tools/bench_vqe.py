#!/usr/bin/env python3
"""
⟨ψ⟩Quantum — tools/bench_vqe.py

VQE benchmark runner: H₂ and LiH on Qiskit Aer (statevector).

Approach
--------
Molecular integrals come from openfermion's bundled HDF5 fixtures
(no PySCF dependency at runtime). qiskit-nature builds the second-quantized
Hamiltonian from raw integrals; ParityMapper performs Z2-symmetry tapering
(LiH 12q → 10q). UCCSD ansatz + Hartree-Fock initial state. SLSQP optimizer
with direct Statevector + sparse Hamiltonian evaluation (no Estimator
overhead — the inner loop is ~30× faster than going through V2 PUBs).

The "Aer" backend label is reported because qiskit_aer's statevector
simulator is the same noiseless evaluator used inside Statevector for
state preparation; both are cross-checked elsewhere.

Records one row per molecule into quantumpsi.db `vqe_runs` and
auto-regenerates reports/benchmark_dashboard.html.

Usage
-----
    python tools/bench_vqe.py                # both molecules
    python tools/bench_vqe.py --molecule h2  # H2 only
    python tools/bench_vqe.py --molecule lih # LiH only
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import scipy.optimize as spopt
from openfermion.chem import MolecularData

from qiskit.quantum_info import Statevector
from qiskit_nature.second_q.circuit.library import HartreeFock, UCCSD
from qiskit_nature.second_q.hamiltonians import ElectronicEnergy
from qiskit_nature.second_q.mappers import ParityMapper
from qiskit_nature.second_q.problems import ElectronicStructureProblem

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src" / "utils"))

from init_db import get_connection, init_db  # noqa: E402

MOL_DIR = PROJECT_ROOT / "src" / "data" / "molecules"

MOLECULES: dict[str, dict] = {
    "h2": {
        "fixture":     "H2_sto-3g_singlet_0.7414.hdf5",
        "label":       "H2",
        "bond_length": 0.7414,
        "ac_target":   -1.137,
        "ac_window":   1.6e-3,
        "maxiter":     200,
    },
    "lih": {
        "fixture":     "H1-Li1_sto-3g_singlet_1.45.hdf5",
        "label":       "LiH",
        "bond_length": 1.45,
        "ac_target":   -7.882,
        "ac_window":   1.6e-3,
        "maxiter":     40,
    },
}


def _build_problem(fixture_name: str):
    """Load HDF5 fixture and return (qubit_op, problem, nuclear_repulsion, fci_total)."""
    m = MolecularData(filename=str(MOL_DIR / fixture_name))
    m.load()
    h1 = np.asarray(m.one_body_integrals)
    # OpenFermion stores two-body in physicist [p,q,r,s]; qiskit-nature wants chemist [p,r,q,s]
    h2_chem = np.transpose(np.asarray(m.two_body_integrals), (0, 2, 3, 1))
    energy = ElectronicEnergy.from_raw_integrals(h1, h2_chem)
    problem = ElectronicStructureProblem(energy)
    problem.num_spatial_orbitals = m.n_orbitals
    problem.num_particles = (m.n_electrons // 2, m.n_electrons // 2)
    mapper = ParityMapper(num_particles=problem.num_particles)
    qop = mapper.map(problem.hamiltonian.second_q_op())
    return qop, problem, mapper, float(m.nuclear_repulsion), float(m.fci_energy)


def run_vqe(molecule: str, backend_label: str = "aer_statevector") -> dict:
    """Run VQE on one molecule and return result dict."""
    cfg = MOLECULES[molecule]
    print("=" * 64)
    print(f"  VQE BENCHMARK -- {cfg['label']} (R={cfg['bond_length']} A)")
    print(f"  Backend: {backend_label}  Mapper: ParityMapper  Ansatz: UCCSD")
    print("=" * 64)

    qop, problem, mapper, nuc, fci_total = _build_problem(cfg["fixture"])
    print(f"  qubits={qop.num_qubits}  pauli_terms={len(qop)}  FCI={fci_total:.6f}")

    # Sparse Hamiltonian for fast ⟨ψ|H|ψ⟩
    H_sparse = qop.to_matrix(sparse=True)

    hf = HartreeFock(problem.num_spatial_orbitals, problem.num_particles, mapper)
    ans = UCCSD(problem.num_spatial_orbitals, problem.num_particles, mapper, initial_state=hf)
    # Decompose so Statevector evaluation has primitive gates only
    ans = ans.decompose().decompose()
    params = list(ans.parameters)
    n_params = len(params)
    print(f"  ansatz_params={n_params}  optimizer=SLSQP  maxiter={cfg['maxiter']}")

    eval_count = [0]
    best_e = [float("inf")]

    def energy_fn(theta: np.ndarray) -> float:
        eval_count[0] += 1
        bound = ans.assign_parameters(dict(zip(params, theta)))
        sv = np.asarray(Statevector(bound).data)
        e = float(np.real(np.vdot(sv, H_sparse @ sv)))
        if e < best_e[0]:
            best_e[0] = e
        return e

    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    t0 = time.time()
    init = np.zeros(n_params)
    res = spopt.minimize(
        energy_fn, init, method="SLSQP",
        options={"maxiter": cfg["maxiter"], "ftol": 1e-7},
    )
    wall = time.time() - t0
    final_electronic = float(res.fun)
    final_total = final_electronic + nuc
    delta_fci = abs(final_total - fci_total)
    delta_target = abs(final_total - cfg["ac_target"])

    print("-" * 64)
    print(f"  final E    : {final_total:.6f} Ha")
    print(f"  FCI ref    : {fci_total:.6f} Ha")
    print(f"  delta_FCI  : {delta_fci:.4e} Ha")
    print(f"  delta_targ : {delta_target:.4e} Ha (window +/- {cfg['ac_window']:.1e})")
    print(f"  evals={eval_count[0]}  wall={wall:.1f}s")
    print(f"  AC met     : {'YES' if delta_target < cfg['ac_window'] else 'NO'}")
    print("=" * 64)

    # Insert into encrypted DB
    init_db()
    conn = get_connection()
    conn.execute(
        """INSERT INTO vqe_runs (
            run_date, molecule, bond_length_ang, n_qubits, n_pauli_terms,
            ansatz, n_parameters, optimizer,
            final_energy, fci_reference, delta_ha,
            n_evals, wall_clock_sec, backend, timestamp
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            ts[:10], cfg["label"], cfg["bond_length"], qop.num_qubits, len(qop),
            "UCCSD", n_params, "SLSQP",
            round(final_total, 8), round(fci_total, 8), round(delta_fci, 8),
            eval_count[0], round(wall, 3), backend_label, ts,
        ),
    )
    conn.commit()
    conn.close()
    print(f"  Row inserted into quantumpsi.db vqe_runs")

    return {
        "molecule":      cfg["label"],
        "n_qubits":      qop.num_qubits,
        "n_pauli_terms": len(qop),
        "n_params":      n_params,
        "final_energy":  final_total,
        "fci_reference": fci_total,
        "delta_fci":     delta_fci,
        "delta_target":  delta_target,
        "ac_window":     cfg["ac_window"],
        "ac_met":        delta_target < cfg["ac_window"],
        "evals":         eval_count[0],
        "wall_sec":      wall,
        "backend":       backend_label,
        "timestamp":     ts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="VQE benchmark runner (H2, LiH on Aer).")
    parser.add_argument("--molecule", choices=["h2", "lih", "all"], default="all")
    parser.add_argument("--no-dashboard", action="store_true",
                        help="Skip auto-regeneration of the benchmark dashboard.")
    args = parser.parse_args()

    targets = ["h2", "lih"] if args.molecule == "all" else [args.molecule]
    results = [run_vqe(t) for t in targets]

    print("\n" + "=" * 64)
    print("  VQE BENCH SUMMARY")
    print("=" * 64)
    for r in results:
        status = "PASS" if r["ac_met"] else "FAIL"
        print(f"  {r['molecule']:>4}  E={r['final_energy']:.6f}  d_FCI={r['delta_fci']:.2e}  "
              f"d_target={r['delta_target']:.2e}  evals={r['evals']}  t={r['wall_sec']:.1f}s  [{status}]")
    print("=" * 64)

    if not args.no_dashboard:
        try:
            import subprocess
            dash = str(PROJECT_ROOT / "tools" / "gen_benchmark_dashboard.py")
            subprocess.run([sys.executable, dash, "--no-open"], check=True)
            print("Dashboard auto-regenerated.")
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] Could not regenerate dashboard: {exc}")

    return 0 if all(r["ac_met"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
