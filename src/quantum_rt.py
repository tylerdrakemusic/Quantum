"""Compatibility shim for the pre-package random API."""

import warnings

warnings.warn(
    "quantum_rt is deprecated; import random utilities from quantum_toolkit instead",
    DeprecationWarning,
    stacklevel=2,
)

from quantum_toolkit import (  # noqa: E402
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
