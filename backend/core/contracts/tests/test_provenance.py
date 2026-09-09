from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.provenance import (
    DEFAULT_OPM_IMAGE,
    OPM_IMAGE_ENV,
    git_commit,
    git_dirty,
    opm_image,
    package_versions,
    python_version,
)


def test_git_commit_returns_none_outside_repository(tmp_path: Path) -> None:
    assert git_commit(root=tmp_path) is None


def test_git_dirty_returns_none_outside_repository(tmp_path: Path) -> None:
    assert git_dirty(root=tmp_path) is None


def test_git_commit_returns_none_for_missing_directory(tmp_path: Path) -> None:
    assert git_commit(root=tmp_path / "absent") is None
    assert git_dirty(root=tmp_path / "absent") is None


def test_git_commit_is_hex_when_available() -> None:
    commit = git_commit()
    if commit is None:
        pytest.skip("git недоступен или каталог не является репозиторием")
    assert len(commit) == 40
    assert all(character in "0123456789abcdef" for character in commit)
    assert git_dirty() in (True, False)


def test_opm_image_prefers_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPM_IMAGE_ENV, "registry.local/opm:pinned")

    assert opm_image() == "registry.local/opm:pinned"


def test_opm_image_falls_back_to_project_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(OPM_IMAGE_ENV, raising=False)

    assert opm_image() == DEFAULT_OPM_IMAGE
    assert DEFAULT_OPM_IMAGE == "openporousmedia/opmreleases:latest"


def test_opm_image_ignores_blank_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPM_IMAGE_ENV, "   ")

    assert opm_image() == DEFAULT_OPM_IMAGE


def test_python_version_is_non_empty() -> None:
    value = python_version()

    assert isinstance(value, str)
    assert value.strip()


def test_package_versions_omits_absent_packages() -> None:
    versions = package_versions()

    assert isinstance(versions, dict)
    for name, value in versions.items():
        assert isinstance(name, str) and name
        assert isinstance(value, str) and value.strip()
