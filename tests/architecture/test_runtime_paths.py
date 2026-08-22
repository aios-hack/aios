from pathlib import Path

from backend.core.paths import data_root, out_root, project_root
from backend.presentation.ui_export.base_artifact import DEFAULT_RESPONSE_PATH
from backend.presentation.ui_export.demo import DEFAULT_OUT_DIR
from backend.presentation.ui_export.webdata import DEFAULT_OUT_PATH


def test_runtime_defaults_are_under_project_not_source_package(monkeypatch) -> None:
    for name in ("AIOS_PROJECT_ROOT", "AIOS_DATA_ROOT", "AIOS_OUT_DIR"):
        monkeypatch.delenv(name, raising=False)

    root = project_root()

    assert (root / "pyproject.toml").is_file()
    assert data_root() == root / "data"
    assert out_root() == root / "out"
    for path in (DEFAULT_RESPONSE_PATH, DEFAULT_OUT_DIR, DEFAULT_OUT_PATH):
        assert path.is_relative_to(root)
        assert not path.is_relative_to(root / "src")


def test_out_root_honours_its_own_environment_variable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AIOS_OUT_DIR", str(tmp_path / "results"))
    assert out_root() == (tmp_path / "results").resolve()


def test_data_root_honours_its_own_environment_variable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AIOS_DATA_ROOT", str(tmp_path / "inputs"))
    assert data_root() == (tmp_path / "inputs").resolve()
