from __future__ import annotations


def relative_error(delta_stock: float, delta_flow: float) -> float:
    denom = abs(delta_flow)
    return 0.0 if denom == 0.0 else abs(delta_stock - delta_flow) / denom


__all__ = ["relative_error"]
