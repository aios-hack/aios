from __future__ import annotations

from pathlib import Path

import pytest

from backend.shared.errors import ConfigurationError
from backend.shared.settings import (
    DEFAULT_FINAL_FIXED_POINT_CAP,
    DEFAULT_SEARCH_FIXED_POINT_CAP,
    DEFAULT_SEED,
    ENV_VARIABLES,
    Settings,
)


def test_an_empty_environment_still_yields_usable_defaults() -> None:
    settings = Settings.from_env({})

    assert settings.seed == DEFAULT_SEED
    assert settings.search_fixed_point_cap == DEFAULT_SEARCH_FIXED_POINT_CAP
    assert settings.final_fixed_point_cap == DEFAULT_FINAL_FIXED_POINT_CAP
    assert settings.risk_aversion_beta == 0.0
    assert settings.constraints_path == Path("config/competition-constraints.json")
    assert settings.docs_root is None
    assert settings.openrouter_api_key is None


def test_settings_are_frozen() -> None:
    settings = Settings.from_env({})

    with pytest.raises(Exception):
        settings.seed = 1  # type: ignore[misc]


def test_paths_come_from_the_environment(tmp_path: Path) -> None:
    settings = Settings.from_env(
        {
            "AIOS_PROJECT_ROOT": str(tmp_path),
            "AIOS_DATA_ROOT": str(tmp_path / "d"),
            "AIOS_OUT_DIR": str(tmp_path / "o"),
            "AIOS_DOCS_ROOT": str(tmp_path / "docs"),
        }
    )

    assert settings.project_root == tmp_path.resolve()
    assert settings.data_root == (tmp_path / "d").resolve()
    assert settings.out_root == (tmp_path / "o").resolve()
    assert settings.docs_root == tmp_path / "docs"


def test_data_and_out_hang_off_the_project_root_when_unset(tmp_path: Path) -> None:
    settings = Settings.from_env({"AIOS_PROJECT_ROOT": str(tmp_path)})

    assert settings.data_root == tmp_path.resolve() / "data"
    assert settings.out_root == tmp_path.resolve() / "out"


@pytest.mark.parametrize("value", ["0", "-1", "two", " "])
def test_an_unusable_cap_is_refused_not_silently_defaulted(value: str) -> None:
    with pytest.raises(ConfigurationError) as error:
        Settings.from_env({"AIOS_SEARCH_FIXED_POINT_CAP": value})

    assert "AIOS_SEARCH_FIXED_POINT_CAP" in str(error.value)
    assert error.value.details["variable"] == "AIOS_SEARCH_FIXED_POINT_CAP"


def test_caps_are_read_from_the_environment() -> None:
    settings = Settings.from_env(
        {"AIOS_SEARCH_FIXED_POINT_CAP": "6", "AIOS_FINAL_FIXED_POINT_CAP": "12"}
    )

    assert settings.search_fixed_point_cap == 6
    assert settings.final_fixed_point_cap == 12


def test_a_non_integer_seed_names_the_variable() -> None:
    with pytest.raises(ConfigurationError) as error:
        Settings.from_env({"AIOS_SEED": "not a number"})

    assert error.value.details["variable"] == "AIOS_SEED"


def test_blank_values_read_as_absent_not_as_empty_paths() -> None:
    settings = Settings.from_env({"AIOS_LAMBDA_PATH": "   ", "OPENROUTER_API_KEY": ""})

    assert settings.lambda_path is None
    assert settings.openrouter_api_key is None


def test_every_declared_variable_is_unique() -> None:
    assert len(ENV_VARIABLES) == len(set(ENV_VARIABLES))


def test_from_env_reads_only_the_mapping_it_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIOS_SEED", "999")

    assert Settings.from_env({}).seed == DEFAULT_SEED
    assert Settings.from_env().seed == 999
