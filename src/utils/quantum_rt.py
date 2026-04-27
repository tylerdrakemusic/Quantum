"""
⟨ψ⟩Quantum — quantum_rt.py  (Quantum Random Toolkit)

Provides quantum-measurement-seeded random functions that mirror the
standard library (random / secrets) API but draw entropy from real
quantum bitstrings captured in ty_string_cache.txt.

Entropy source
--------------
The ⟨ψ⟩Quantum project maintains rolling backups of quantum measurement
outcomes in:
    f:\\⟨ψ⟩Quantum\\qbackups\\ty_string_cache_<timestamp>.txt
    f:\\⟨ψ⟩Quantum\\src\\data\\qbackups\\ty_string_cache.txt   (latest)

Each line in those files is a binary string (0/1 characters) representing
raw qubit measurement results.  This module concatenates all lines into a
single bitstream and consumes bits sequentially.  When the cache is
exhausted it falls back to the `secrets` module transparently.

Public API (mirrors original quantum_rt contract)
-------------------------------------------------
    qRandom()                    → float in [0, 1)
    qRax(a, b)                   → int in [a, b]   (inclusive)
    qhoice(seq)                  → one element from seq
    quuffle(lst)                 → shuffles lst in-place (returns None)
    qsample(population, k)       → list of k unique elements
    qpermute(seq)                → new list — random permutation of seq
    qRandomBool()                → True or False
    qRandomBitstring(n)          → str of n '0'/'1' characters

All functions are safe to call in isolation; no global state leaks outside
this module beyond the shared _BitStream cursor.

SECURITY: This module is read-only with respect to the cache files.
          It never writes, logs, or transmits generated values.
"""

from __future__ import annotations

import logging
import math
import secrets
import sys
from pathlib import Path
from typing import Any, MutableSequence, Sequence, TypeVar

_T = TypeVar("_T")

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Locate the most recent cache file
# ---------------------------------------------------------------------------

def _find_cache_files() -> list[Path]:
    """Return all known ty_string_cache files, newest first by filename."""
    candidates: list[Path] = []

    # Resolve the ⟨ψ⟩Quantum root (this file lives inside it)
    _this = Path(__file__).resolve()
    # Walk up until we find a directory whose name contains 'Quantum'
    _q_root: Path | None = None
    for ancestor in _this.parents:
        if "Quantum" in ancestor.name or "\u27e8" in ancestor.name:
            _q_root = ancestor
            break

    if _q_root is None:
        # Fallback: assume standard relative layout
        _q_root = _this.parent.parent.parent  # src/utils -> src -> project root

    # Preferred: live cache
    live = _q_root / "src" / "data" / "qbackups" / "ty_string_cache.txt"
    if live.exists():
        candidates.append(live)

    # Timestamped backups
    backup_dir = _q_root / "qbackups"
    if backup_dir.is_dir():
        backups = sorted(
            backup_dir.glob("ty_string_cache_*.txt"),
            key=lambda p: p.stem,
            reverse=True,
        )
        candidates.extend(backups)

    return candidates


def _load_bitstream() -> str:
    """Load and concatenate all bitstrings from the best available cache."""
    files = _find_cache_files()
    if not files:
        _logger.warning("quantum_rt: no ty_string_cache files found — using secrets fallback")
        return ""

    bits_parts: list[str] = []
    for cache_path in files:
        try:
            with open(cache_path, encoding="utf-8", errors="ignore") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if line and all(c in "01" for c in line):
                        bits_parts.append(line)
        except OSError as exc:
            _logger.debug("quantum_rt: could not read %s: %s", cache_path, exc)

    if not bits_parts:
        _logger.warning("quantum_rt: cache files contained no valid bitstrings")
        return ""

    combined = "".join(bits_parts)
    _logger.debug("quantum_rt: loaded %d bits from %d file(s)", len(combined), len(files))
    return combined


# ---------------------------------------------------------------------------
# BitStream — sequential bit consumer with secrets fallback
# ---------------------------------------------------------------------------

class _BitStream:
    """Thread-unsafe sequential consumer of a pre-loaded quantum bitstring."""

    def __init__(self) -> None:
        self._bits: str = _load_bitstream()
        self._cursor: int = 0
        self._exhausted_warned: bool = False

    def _next_bits(self, n: int) -> str:
        """Return n bits from the stream, using secrets if cache exhausted."""
        available = len(self._bits) - self._cursor
        if available >= n:
            chunk = self._bits[self._cursor : self._cursor + n]
            self._cursor += n
            return chunk
        # Cache exhausted — fall back to secrets for remaining bits
        if not self._exhausted_warned:
            _logger.info(
                "quantum_rt: cache exhausted after %d bits — using secrets fallback",
                self._cursor,
            )
            self._exhausted_warned = True
        # secrets.token_bits is not in all Python versions; use token_bytes
        n_bytes = math.ceil(n / 8)
        raw = secrets.token_bytes(n_bytes)
        bits = bin(int.from_bytes(raw, "big"))[2:].zfill(n_bytes * 8)
        return bits[:n]

    def read_uint(self, n_bits: int) -> int:
        """Read n_bits and return as an unsigned integer."""
        return int(self._next_bits(n_bits), 2)

    def read_float(self) -> float:
        """Return a float in [0, 1) using 53 bits (matches double precision mantissa)."""
        value = self.read_uint(53)
        return value / (2**53)

    def read_bool(self) -> bool:
        return self._next_bits(1) == "1"

    def read_bits(self, n: int) -> str:
        return self._next_bits(n)

    def read_index(self, upper: int) -> int:
        """Return a uniformly distributed integer in [0, upper) using rejection sampling."""
        if upper <= 0:
            raise ValueError("upper must be > 0")
        if upper == 1:
            # Consume at least 1 bit for consistency
            self._next_bits(1)
            return 0
        n_bits = math.ceil(math.log2(upper + 1))
        # Use enough bits but reject values >= upper to maintain uniformity
        limit = 2**n_bits
        while True:
            val = self.read_uint(n_bits)
            # Avoid bias by rejecting values in the modulo tail
            cutoff = limit - (limit % upper)
            if val < cutoff:
                return val % upper


# Module-level singleton
_stream = _BitStream()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def qRandom() -> float:
    """Return a quantum-seeded float in [0, 1)."""
    return _stream.read_float()


def qRax(a: int, b: int) -> int:
    """Return a quantum-seeded integer in [a, b] inclusive."""
    if a > b:
        raise ValueError(f"qRax: a ({a}) must be <= b ({b})")
    if a == b:
        return a
    span = b - a + 1
    return a + _stream.read_index(span)


def qhoice(seq: Sequence[_T]) -> _T:
    """Return a single element chosen uniformly at random from seq."""
    if not seq:
        raise IndexError("qhoice from an empty sequence")
    return seq[_stream.read_index(len(seq))]


def quuffle(lst: MutableSequence[Any]) -> None:
    """Shuffle lst in-place (Fisher-Yates), modelled after random.shuffle."""
    n = len(lst)
    for i in range(n - 1, 0, -1):
        j = _stream.read_index(i + 1)
        lst[i], lst[j] = lst[j], lst[i]


def qsample(population: Sequence[_T], k: int) -> list[_T]:
    """Return a list of k unique elements chosen from population."""
    n = len(population)
    if k < 0 or k > n:
        raise ValueError(f"qsample: k ({k}) is out of range for population of size {n}")
    # Build a working copy and partial-shuffle to select k elements
    pool = list(population)
    result: list[_T] = []
    for i in range(k):
        j = i + _stream.read_index(n - i)
        pool[i], pool[j] = pool[j], pool[i]
        result.append(pool[i])
    return result


def qpermute(seq: Sequence[_T]) -> list[_T]:
    """Return a new list containing all elements of seq in a random order."""
    result = list(seq)
    quuffle(result)
    return result


def qRandomBool() -> bool:
    """Return True or False with equal probability."""
    return _stream.read_bool()


def qRandomBitstring(n: int) -> str:
    """Return a string of n '0'/'1' characters from the quantum cache."""
    if n < 0:
        raise ValueError(f"qRandomBitstring: n must be >= 0, got {n}")
    return _stream.read_bits(n)


# ---------------------------------------------------------------------------
# Module-level diagnostics
# ---------------------------------------------------------------------------

def _cache_status() -> dict:
    """Return a dict with cache statistics (for debugging)."""
    return {
        "total_bits": len(_stream._bits),
        "consumed_bits": _stream._cursor,
        "remaining_bits": max(0, len(_stream._bits) - _stream._cursor),
        "exhausted_warned": _stream._exhausted_warned,
    }
