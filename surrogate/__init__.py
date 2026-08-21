"""Compatibility package. New code lives in :mod:`aios_backend.ml.surrogate`."""

from aios_backend.ml import surrogate as _implementation
from aios_backend.ml.surrogate import *

__all__ = _implementation.__all__
__path__ = _implementation.__path__
