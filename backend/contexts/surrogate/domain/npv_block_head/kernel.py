from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from torch import Tensor

from backend.contexts.surrogate.domain.errors import BlockNpvHeadError


FORMAT = "aios.surrogate-block-npv-head.v1"
LEGACY_IMPLEMENTATION_HASHES = {
    "c95a68493476fea29baf1527fc16d3fa8178a13f47c79551cee701dd02e5ea68",
    "dd97cba949a664eafe4c45900777e1dfd805b63b015109e0c4bb7ff47fcf9bfb",
    "95f3dc77460ccbf578a5f1c96b66fc24fa45de0ecaf7fe898f0ba2cb46ed4ca2",
}
Mode = Literal["joint", "additive"]
DEFAULT_BLOCKS = (
    ("global", 0, 84),
    ("temporal", 84, 1260),
    ("well", 1260, 2908),
    ("economic", 2908, 4406),
)


def block_implementation_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _block_kernel(
    left: Tensor,
    right: Tensor,
    *,
    blocks: tuple[tuple[str, int, int], ...],
    active_widths: tuple[int, ...],
    weights: tuple[float, ...],
    mode: Mode,
) -> Tensor:
    components = []
    component_weights = []
    for (_, start, stop), width, weight in zip(
        blocks, active_widths, weights, strict=True
    ):
        if weight == 0.0:
            continue
        components.append(left[:, start:stop] @ right[:, start:stop].T / width)
        component_weights.append(weight)
    if mode == "joint":
        mixed = sum(
            weight * item
            for weight, item in zip(component_weights, components, strict=True)
        )
        return (1.0 + mixed).square()
    if mode == "additive":
        return sum(
            weight * (1.0 + item).square()
            for weight, item in zip(component_weights, components, strict=True)
        )
    raise BlockNpvHeadError(f"unknown block kernel mode: {mode}")


__all__ = [
    "DEFAULT_BLOCKS",
    "FORMAT",
    "LEGACY_IMPLEMENTATION_HASHES",
    "Mode",
    "block_implementation_hash",
]
