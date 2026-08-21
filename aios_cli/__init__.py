"""Compatibility package. New code lives in :mod:`aios_backend.presentation.cli`."""

from aios_backend.presentation import cli as _implementation
from aios_backend.presentation.cli import *

__all__ = getattr(_implementation, "__all__", ())
__path__ = _implementation.__path__
