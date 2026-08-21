"""Compatibility package. New code lives in :mod:`aios_backend.domain.policy`."""

from aios_backend.domain import policy as _implementation
from aios_backend.domain.policy import *

__all__ = _implementation.__all__
__path__ = _implementation.__path__
