from __future__ import annotations

from pathlib import Path

import pytest

import conftest
from backend.core.paths import project_root


def test_repo_root_is_the_directory_with_pyproject() -> None:
    root = conftest.repo_root()
    assert (root / "pyproject.toml").is_file()
    assert root == project_root()


def test_base_run_candidates_never_leave_the_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(conftest.BASE_RUN_ENV_VAR, raising=False)
    monkeypatch.delenv("AIOS_DATA_ROOT", raising=False)
    root = conftest.repo_root()
    candidates = conftest._base_run_candidates()
    assert candidates
    for candidate in candidates:
        assert candidate.is_relative_to(root), candidate


def test_no_sibling_directory_is_scanned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(conftest.BASE_RUN_ENV_VAR, raising=False)
    monkeypatch.delenv("AIOS_DATA_ROOT", raising=False)
    root = conftest.repo_root()
    siblings = {path.resolve() for path in root.parent.iterdir() if path.is_dir()}
    siblings.discard(root)
    for candidate in conftest._base_run_candidates():
        for sibling in siblings:
            assert not candidate.is_relative_to(sibling), (candidate, sibling)


def test_environment_override_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(conftest.BASE_RUN_ENV_VAR, str(tmp_path))
    assert conftest._base_run_candidates() == (tmp_path.resolve(),)


def test_missing_base_run_reports_a_reason_instead_of_a_foreign_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(conftest.BASE_RUN_ENV_VAR, str(tmp_path / "absent"))
    assert conftest.base_run_dir() is None
    assert conftest.base_run_output_dir() is None
    reason = conftest.base_run_missing_reason()
    assert reason is not None
    assert conftest.BASE_RUN_ENV_VAR in reason


def test_a_foreign_base_run_is_not_picked_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    foreign = tmp_path / "other-repo" / "data" / "base_run"
    (foreign / "deck").mkdir(parents=True)
    (foreign / "runs").mkdir(parents=True)
    monkeypatch.delenv(conftest.BASE_RUN_ENV_VAR, raising=False)
    monkeypatch.delenv("AIOS_DATA_ROOT", raising=False)
    found = conftest.base_run_dir()
    if found is not None:
        assert found != foreign
        assert found.is_relative_to(conftest.repo_root())
