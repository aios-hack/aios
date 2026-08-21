"""Compatibility package. New code lives in :mod:`aios_backend.domain.economics`."""

from aios_backend.domain import economics as _implementation
from aios_backend.domain.economics import *

__all__ = _implementation.__all__
__path__ = _implementation.__path__
