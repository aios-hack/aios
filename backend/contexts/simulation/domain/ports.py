from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class WellStockSource(Protocol):
    @property
    def source_wells(self) -> tuple[str, ...]: ...


__all__ = ["WellStockSource"]
