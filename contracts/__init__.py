"""Compatibility package. New code lives in :mod:`aios_backend.core.contracts`."""

from aios_backend.core import contracts as _implementation
from aios_backend.core.contracts import *

__all__ = _implementation.__all__
__path__ = _implementation.__path__
