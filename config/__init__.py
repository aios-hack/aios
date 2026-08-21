"""Compatibility package. New code lives in :mod:`aios_backend.domain.configuration`."""

from aios_backend.domain import configuration as _implementation
from aios_backend.domain.configuration import *

__all__ = _implementation.__all__
__path__ = _implementation.__path__
