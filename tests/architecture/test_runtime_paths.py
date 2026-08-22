from pathlib import Path

from backend.core.paths import data_root, project_root
from backend.presentation.ui_export.base_artifact import DEFAULT_RESPONSE_PATH
from backend.presentation.ui_export.demo import DEFAULT_OUT_DIR
from backend.presentation.ui_export.webdata import DEFAULT_OUT_PATH


def test_runtime_defaults_are_under_project_not_source_package() -> None:
    root = project_root()

    assert (root / "pyproject.toml").is_file()
    assert data_root() == root / "data"
    for path in (DEFAULT_RESPONSE_PATH, DEFAULT_OUT_DIR, DEFAULT_OUT_PATH):
        assert path.is_relative_to(root)
        assert not path.is_relative_to(root / "src")
