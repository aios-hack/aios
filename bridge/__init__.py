"""Compatibility package. New code lives in :mod:`aios_backend.infrastructure.opm`."""

from aios_backend.infrastructure import opm as _implementation
from aios_backend.infrastructure.opm import *

__all__ = _implementation.__all__
__path__ = _implementation.__path__
