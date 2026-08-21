"""Compatibility package. New code lives in :mod:`aios_backend.domain.schedule`."""

from aios_backend.domain import schedule as _implementation
from aios_backend.domain.schedule import *

__all__ = _implementation.__all__
__path__ = _implementation.__path__
