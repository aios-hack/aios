from __future__ import annotations

from pathlib import Path

import pytest

from backend.application.jarvis.artifacts import ArtifactStore


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "frontend" / "public" / "data").is_dir():
            return parent
    raise RuntimeError("корень репозитория с frontend/public/data не найден")


@pytest.fixture(scope="session")
def data_root() -> Path:
    return repo_root() / "frontend" / "public" / "data"


@pytest.fixture(scope="session")
def store(data_root: Path) -> ArtifactStore:
    return ArtifactStore(data_root)


@pytest.fixture(scope="session")
def knowledge_root() -> Path:
    return repo_root() / "frontend" / "public" / "jarvis" / "knowledge"


@pytest.fixture(scope="session")
def fixtures_root() -> Path:
    return repo_root() / "frontend" / "public" / "jarvis" / "fixtures"
