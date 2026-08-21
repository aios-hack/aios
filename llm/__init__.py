"""Compatibility package. New code lives in :mod:`aios_backend.infrastructure.llm`."""

from aios_backend.infrastructure import llm as _implementation
from aios_backend.infrastructure.llm import *

__all__ = _implementation.__all__
__path__ = _implementation.__path__
