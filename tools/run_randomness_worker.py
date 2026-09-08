from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from quantum_randomness_service.provider import VerifiedCacheStore
from quantum_randomness_service.worker import (
    IBMQuantumProvider,
    TigrisS3Publisher,
    run_scheduled_worker,
)

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    signing_key = os.environ.get("QUANTUM_MANIFEST_SIGNING_KEY", "").encode()
    if not signing_key:
        raise RuntimeError("QUANTUM_MANIFEST_SIGNING_KEY is not configured")
    policy = json.loads((ROOT / "src" / "config" / "execution_policy.json").read_text(encoding="utf-8"))
    schedule = policy["schedules"]["quantum_cache_fill_monthly"]
    store = VerifiedCacheStore(
        Path(os.environ.get("QUANTUM_CACHE_DIR", "/data/verified")), signing_key
    )
    run_scheduled_worker(
        store=store,
        provider=IBMQuantumProvider(),
        publisher=TigrisS3Publisher.from_environment(),
        capacity_bits=int(os.environ.get("QUANTUM_CACHE_CAPACITY_BITS", "8388608")),
        refill_bits=int(os.environ.get("QUANTUM_REFILL_BITS", "520192")),
        day=int(schedule["day_of_month"]),
        hour=int(schedule["hour"]),
        minute=int(schedule["minute"]),
    )

if __name__ == "__main__":
    main()