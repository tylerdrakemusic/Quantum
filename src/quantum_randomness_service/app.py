from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from .limits import RateLimiter
from .provider import VerifiedCacheStore, random_bytes

MAX_BYTES = 1024
MAX_BITS = MAX_BYTES * 8


def create_app(config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        FLY_BEARER_TOKEN=os.environ.get("FLY_BEARER_TOKEN", ""),
        QUANTUM_MANIFEST_SIGNING_KEY=os.environ.get("QUANTUM_MANIFEST_SIGNING_KEY", "").encode(),
        QUANTUM_CACHE_DIR=os.environ.get("QUANTUM_CACHE_DIR", "src/data/liveCache/verified"),
        QUANTUM_MANIFEST_URL=os.environ.get("QUANTUM_MANIFEST_URL", ""),
    )
    if config:
        app.config.update(config)
        if isinstance(app.config["FLY_BEARER_TOKEN"], str):
            app.config["FLY_BEARER_TOKEN"] = app.config["FLY_BEARER_TOKEN"]
    limiter = RateLimiter()
    signing_key = app.config["QUANTUM_MANIFEST_SIGNING_KEY"]
    if isinstance(signing_key, str):
        signing_key = signing_key.encode()
    store = VerifiedCacheStore(Path(app.config["QUANTUM_CACHE_DIR"]), signing_key) if signing_key else None

    def authorized() -> bool:
        provided = request.headers.get("Authorization", "")
        expected = f"Bearer {app.config['FLY_BEARER_TOKEN']}"
        return bool(app.config["FLY_BEARER_TOKEN"]) and hmac.compare_digest(provided, expected)

    def guarded(units: int = 1) -> tuple[Any, int] | None:
        if not authorized():
            return jsonify({"error": "unauthorized"}), 401
        token = app.config["FLY_BEARER_TOKEN"]
        if not limiter.allow(token, units=units):
            return jsonify({"error": "rate_limit_exceeded"}), 429
        return None

    def length(name: str, default: int = 1, maximum: int = MAX_BYTES) -> int:
        try:
            value = int(request.args.get(name, default))
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be an integer")
        if value < 1 or (name == "n" and value > maximum):
            raise ValueError(f"{name} is outside the allowed range")
        return value

    @app.get("/health")
    def health() -> Any:
        return jsonify({"status": "ok"})

    @app.get("/v1/status")
    def status() -> Any:
        if store and app.config["QUANTUM_MANIFEST_URL"]:
            try:
                store.refresh_from_url(app.config["QUANTUM_MANIFEST_URL"])
            except Exception:
                pass
        provenance = store.status() if store else {"source": "os_csprng", "quantum_cache": "unavailable"}
        return jsonify({"service": "quantum-randomness", "provenance": provenance})

    @app.get("/v1/bytes")
    def bytes_endpoint() -> Any:
        try:
            requested = int(request.args.get("n", 1))
        except (TypeError, ValueError):
            requested = 0
        denied = guarded(units=requested if requested > 0 else 1)
        if denied:
            return denied
        if requested < 1:
            return jsonify({"error": "n must be an integer"}), 400
        if requested > MAX_BYTES:
            return jsonify({"error": "request exceeds 1 KiB limit"}), 413
        try:
            count = length("n")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if store and app.config["QUANTUM_MANIFEST_URL"]:
            try:
                store.refresh_from_url(app.config["QUANTUM_MANIFEST_URL"])
            except Exception:
                pass
        value, provenance = random_bytes(count, store)
        return jsonify({"bytes_hex": value.hex(), "provenance": provenance})

    @app.get("/v1/bits")
    def bits_endpoint() -> Any:
        try:
            requested = int(request.args.get("n", 1))
        except (TypeError, ValueError):
            requested = 0
        denied = guarded(units=max(1, (requested + 7) // 8))
        if denied:
            return denied
        if requested > MAX_BITS:
            return jsonify({"error": "request exceeds 1 KiB limit"}), 413
        try:
            count = length("n", maximum=MAX_BITS)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if store and app.config["QUANTUM_MANIFEST_URL"]:
            try:
                store.refresh_from_url(app.config["QUANTUM_MANIFEST_URL"])
            except Exception:
                pass
        value, provenance = random_bytes((count + 7) // 8, store)
        return jsonify({"bits": bin(int.from_bytes(value, "big"))[2:].zfill(len(value) * 8)[:count], "provenance": provenance})

    @app.get("/v1/ints")
    def ints_endpoint() -> Any:
        denied = guarded(units=8)
        if denied:
            return denied
        try:
            minimum, maximum = int(request.args["min"]), int(request.args["max"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "min and max must be integers"}), 400
        if minimum > maximum or maximum - minimum > (1 << 31):
            return jsonify({"error": "invalid integer range"}), 400
        if store and app.config["QUANTUM_MANIFEST_URL"]:
            try:
                store.refresh_from_url(app.config["QUANTUM_MANIFEST_URL"])
            except Exception:
                pass
        value, provenance = random_bytes(8, store)
        result = minimum + (int.from_bytes(value, "big") % (maximum - minimum + 1))
        return jsonify({"value": result, "provenance": provenance})

    @app.get("/v1/bool")
    def bool_endpoint() -> Any:
        denied = guarded(units=1)
        if denied:
            return denied
        if store and app.config["QUANTUM_MANIFEST_URL"]:
            try:
                store.refresh_from_url(app.config["QUANTUM_MANIFEST_URL"])
            except Exception:
                pass
        value, provenance = random_bytes(1, store)
        return jsonify({"value": bool(value[0] & 1), "provenance": provenance})

    return app


app = create_app()
