"""Public random API backed by the legacy compatibility implementation."""

from utils.quantum_rt import (
    qRandom,
    qRandomBitstring,
    qRandomBool,
    qRax,
    qhoice,
    qpermute,
    qsample,
    quuffle,
)

__all__ = (
    "qRandom",
    "qRax",
    "qhoice",
    "quuffle",
    "qsample",
    "qpermute",
    "qRandomBool",
    "qRandomBitstring",
)
