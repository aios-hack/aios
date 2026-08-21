"""Compatibility package. New code lives in :mod:`aios_backend.domain.connectivity`."""

from aios_backend.domain import connectivity as _implementation
from aios_backend.domain.connectivity import *

__all__ = _implementation.__all__
__path__ = _implementation.__path__
