"""Compatibility package. New code lives in :mod:`aios_backend.presentation.ui_export`."""

from aios_backend.presentation import ui_export as _implementation
from aios_backend.presentation.ui_export import *

__all__ = getattr(_implementation, "__all__", ())
__path__ = _implementation.__path__
