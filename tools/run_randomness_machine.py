from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
API_ENV = {
    "FLY_BEARER_TOKEN",
    "QUANTUM_MANIFEST_SIGNING_KEY",
    "QUANTUM_CACHE_DIR",
    "QUANTUM_MANIFEST_URL",
}
WORKER_ONLY_ENV = {
    "IBM_CLOUD_API_KEY",
    "IBM_QUANTUM_INSTANCE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "TIGRIS_ENDPOINT",
    "QUANTUM_MANIFEST_SIGNING_KEY",
    "QUANTUM_CACHE_DIR",
    "QUANTUM_CACHE_CAPACITY_BITS",
    "QUANTUM_REFILL_BITS",
}


def api_environment(environment: dict[str, str] | None = None) -> dict[str, str]:
    """Return API configuration while excluding worker-only credentials."""
    values = dict(environment or os.environ)
    return {name: values[name] for name in API_ENV if name in values}


def worker_environment(environment: dict[str, str] | None = None) -> dict[str, str]:
    """Return only provider, signing, and worker configuration variables."""
    values = dict(environment or os.environ)
    return {name: values[name] for name in WORKER_ONLY_ENV if name in values}


def main() -> None:
    """Run the API and refill worker on one Fly machine and mounted volume."""
    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "gunicorn",
            "--bind",
            "0.0.0.0:8211",
            "--workers",
            "1",
            "quantum_randomness_service.app:app",
        ],
        cwd=ROOT,
        env=api_environment(),
    )
    worker = subprocess.Popen(
        [sys.executable, "tools/run_randomness_worker.py"],
        cwd=ROOT,
        env=worker_environment(),
    )
    processes = (api, worker)

    def stop_children(*_signals: int) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, stop_children)
    signal.signal(signal.SIGINT, stop_children)
    try:
        while True:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    stop_children()
                    raise SystemExit(return_code)
            time.sleep(1)
    finally:
        stop_children()
        for process in processes:
            process.wait()


if __name__ == "__main__":
    main()