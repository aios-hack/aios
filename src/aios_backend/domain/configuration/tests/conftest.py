from __future__ import annotations

import pytest

from aios_backend.core.contracts import (
    DEFAULT_NORMATIVES_2007,
    ArtifactHashes,
    Config,
    NormativeSet,
)

from aios_backend.domain.configuration import default_config

GLOBAL_SEED = 20260815


def a_hash(marker: str) -> str:
    return (marker * 64)[:64]


@pytest.fixture
def hashes() -> ArtifactHashes:
    return ArtifactHashes(
        deck_hash=a_hash("a"),
        history_prefix_hash=a_hash("b"),
        summary_spec_hash=a_hash("c"),
        groups_hash=a_hash("d"),
        dataset_version_hash=a_hash("e"),
        surrogate_checkpoint_hash=a_hash("f"),
    )


@pytest.fixture
def normatives() -> NormativeSet:
    return NormativeSet(esp_catalog=(), **DEFAULT_NORMATIVES_2007)


@pytest.fixture
def config(normatives: NormativeSet, hashes: ArtifactHashes) -> Config:
    return default_config(
        normatives=normatives, hashes=hashes, global_seed=GLOBAL_SEED
    )
