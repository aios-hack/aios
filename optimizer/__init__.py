"""Compatibility package. New code lives in :mod:`aios_backend.application.optimization`."""

from aios_backend.application import optimization as _implementation
from aios_backend.application.optimization import *

__all__ = _implementation.__all__
__path__ = _implementation.__path__
