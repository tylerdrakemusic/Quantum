from __future__ import annotations

import os
import sys
import subprocess
import warnings
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


PUBLIC_RANDOM_API = (
    "qRandom",
    "qRax",
    "qhoice",
    "quuffle",
    "qsample",
    "qpermute",
    "qRandomBool",
    "qRandomBitstring",
)


def test_quantum_toolkit_exports_only_stable_random_api() -> None:
    import quantum_toolkit

    assert quantum_toolkit.__all__ == PUBLIC_RANDOM_API
    assert all(callable(getattr(quantum_toolkit, name)) for name in PUBLIC_RANDOM_API)
    assert not hasattr(quantum_toolkit, "QAOASolver")


def test_public_api_import_does_not_load_the_cache(tmp_path: Path) -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import quantum_toolkit; print(quantum_toolkit.__all__)",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
        env={**os.environ, "PYTHONPATH": str(SRC_ROOT)},
    )

    assert "qRandom" in probe.stdout


def test_legacy_quantum_rt_shim_warns_and_forwards_public_functions() -> None:
    sys.modules.pop("quantum_rt", None)
    sys.path.insert(0, str(SRC_ROOT))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import quantum_rt

    assert any(item.category is DeprecationWarning for item in caught)
    assert quantum_rt.qRandom is not None
    assert quantum_rt.qRandom is __import__("quantum_toolkit").qRandom


def _install_and_probe(source_root: Path, install_target: Path, *pip_args: str) -> str:
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-deps",
        "--no-build-isolation",
        *pip_args,
        str(source_root),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    probe = subprocess.run(
        [sys.executable, "-c", "import quantum_toolkit; print(quantum_toolkit.__all__)"],
        check=True,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(install_target)},
    )
    return probe.stdout.strip()


def test_regular_install_exposes_public_namespace(tmp_path: Path) -> None:
    install_target = tmp_path / "regular"
    install_target.mkdir()

    output = _install_and_probe(SRC_ROOT.parent, install_target, "--target", str(install_target))

    assert "qRandom" in output
    assert "QAOASolver" not in output


def test_editable_install_exposes_public_namespace(tmp_path: Path) -> None:
    venv_root = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv_root)],
        check=True,
    )
    venv_python = venv_root / ("Scripts" if os.name == "nt" else "bin") / "python"
    subprocess.run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-build-isolation",
            "--editable",
            str(SRC_ROOT.parent),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    metadata = subprocess.run(
        [str(venv_python), "-m", "pip", "show", "quantum-toolkit"],
        check=True,
        capture_output=True,
        text=True,
    )
    probe = subprocess.run(
        [
            str(venv_python),
            "-c",
            "import quantum_toolkit; print(quantum_toolkit.__all__)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    location_fields = {
        "Editable project location:",
        "Location:",
    }
    assert any(
        line.partition(":")[0] + ":" in location_fields
        and line.partition(":")[2].strip()
        for line in metadata.stdout.splitlines()
    )
    assert "qRandom" in probe.stdout
    assert "QAOASolver" not in probe.stdout
