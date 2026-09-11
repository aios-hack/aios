from __future__ import annotations

from pathlib import Path

import torch

from backend.contexts.surrogate.domain.errors import BlockNpvHeadError
from backend.contexts.surrogate.domain.npv_block_head.head import BlockKernelNpvHead
from backend.contexts.surrogate.domain.npv_block_head.kernel import FORMAT


def load_direct_npv_head(path: Path | str) -> object:
    from ..npv_head import FORMAT as LEGACY_FORMAT
    from ..npv_head import ScenarioNpvHead

    payload = torch.load(Path(path), map_location="cpu", weights_only=False)
    artifact_format = payload.get("format")
    if artifact_format == FORMAT:
        return BlockKernelNpvHead.load(path)
    if artifact_format == LEGACY_FORMAT:
        return ScenarioNpvHead.load(path)
    raise BlockNpvHeadError(f"unsupported direct NPV artifact: {artifact_format}")


def validate_direct_npv_head_context(
    head: object,
    *,
    context_dataset_hash: str,
    feature_context_sha256: str,
) -> None:
    expected_context = getattr(head, "feature_context_sha256", "")
    if expected_context:
        if expected_context != feature_context_sha256:
            raise BlockNpvHeadError("direct NPV head feature context differs")
    elif getattr(head, "dataset_hash", None) != context_dataset_hash:
        raise BlockNpvHeadError("legacy direct NPV head dataset differs from context")


def direct_npv_feature_set(head: object) -> str:
    if isinstance(head, BlockKernelNpvHead):
        return "economic"
    feature_set = getattr(head, "feature_set", None)
    if feature_set not in {"global", "temporal", "full", "economic"}:
        raise BlockNpvHeadError("direct NPV head feature set is unsupported")
    return str(feature_set)


__all__ = [
    "direct_npv_feature_set",
    "load_direct_npv_head",
    "validate_direct_npv_head_context",
]
