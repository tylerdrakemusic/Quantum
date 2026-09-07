"""VQE chemical-accuracy tests (FR-20260430-vqe-aer-bench).

These exercise the same code path as ``tools/bench_vqe.py``. H2 is fast
(~10s); LiH is slow (~15 min) and is marked ``slow``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

CHEM_ACC = 1.6e-3  # 1 kcal/mol in hartree


@pytest.fixture(scope="module")
def bench_vqe_module():
    import bench_vqe  # type: ignore
    return bench_vqe


def test_h2_chemical_accuracy(bench_vqe_module, tmp_path, monkeypatch) -> None:
    """H2 ground state via VQE within ±1.6e-3 Ha of -1.137 Ha."""
    # Avoid touching the real DB: redirect to a temp DB by setting the
    # connection function to a nop. We just want the energy result.
    monkeypatch.setattr(bench_vqe_module, "init_db", lambda: None)

    class _NopConn:
        def execute(self, *a, **kw): return self
        def commit(self): return None
        def close(self): return None

    monkeypatch.setattr(bench_vqe_module, "get_connection", lambda: _NopConn())

    result = bench_vqe_module.run_vqe("h2")
    assert result["molecule"] == "H2"
    assert abs(result["final_energy"] - (-1.137)) < CHEM_ACC, (
        f"H2 VQE outside chem accuracy: E={result['final_energy']:.6f} "
        f"target=-1.137 ± {CHEM_ACC}"
    )
    assert result["ac_met"] is True


def test_bounded_fixture_and_ansatz_contract(bench_vqe_module) -> None:
    """The bounded benchmark exposes only genuine fixtures and both ansatz choices."""
    assert set(bench_vqe_module.MOLECULES) == {"h2", "lih"}
    assert bench_vqe_module.MOLECULES["h2"]["fixture"] == "H2_sto-3g_singlet_0.7414.hdf5"
    assert bench_vqe_module.MOLECULES["h2"]["bond_length"] == pytest.approx(0.7414)
    assert bench_vqe_module.MOLECULES["lih"]["fixture"] == "H1-Li1_sto-3g_singlet_1.45.hdf5"
    assert bench_vqe_module.MOLECULES["lih"]["bond_length"] == pytest.approx(1.45)
    assert bench_vqe_module.SUPPORTED_ANSATZES == ("UCCSD", "EfficientSU2")


def test_efficient_su2_builder_is_deterministic(bench_vqe_module) -> None:
    """EfficientSU2 uses the documented bounded configuration and seed."""
    ansatz = bench_vqe_module._build_ansatz(
        "EfficientSU2", n_qubits=2, initial_state=None
    )

    assert ansatz.num_qubits == 2
    assert ansatz.reps == 1
    assert ansatz.entanglement == "linear"


@pytest.mark.slow
@pytest.mark.ci_long_running
def test_lih_chemical_accuracy(bench_vqe_module, monkeypatch) -> None:
    """LiH ground state via VQE within ±1.6e-3 Ha of -7.882 Ha. Slow (~15min)."""
    monkeypatch.setattr(bench_vqe_module, "init_db", lambda: None)

    class _NopConn:
        def execute(self, *a, **kw): return self
        def commit(self): return None
        def close(self): return None

    monkeypatch.setattr(bench_vqe_module, "get_connection", lambda: _NopConn())

    result = bench_vqe_module.run_vqe("lih")
    assert result["molecule"] == "LiH"
    assert abs(result["final_energy"] - (-7.882)) < CHEM_ACC, (
        f"LiH VQE outside chem accuracy: E={result['final_energy']:.6f} "
        f"target=-7.882 ± {CHEM_ACC}"
    )
    assert result["ac_met"] is True
