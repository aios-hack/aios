from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from shims import (
    EXTERNAL_ENTRYPOINTS,
    MODULE_SHIMS,
    PACKAGE_SHIMS,
    REMOVAL_DATE,
    REMOVED_IN_WAVE,
)


def _path_of(dotted: str) -> Path:
    return Path(*dotted.split(".")).with_suffix(".py")


def test_the_registry_declares_when_it_dies() -> None:
    assert REMOVED_IN_WAVE == 3
    assert REMOVAL_DATE


@pytest.mark.parametrize("old", sorted(MODULE_SHIMS))
def test_every_registered_shim_exists_on_disk(old: str) -> None:
    assert _path_of(old).is_file(), f"шим {old} записан в реестр, но файла нет"


@pytest.mark.parametrize("old,new", sorted(MODULE_SHIMS.items()))
def test_every_shim_points_at_a_module_that_exists(old: str, new: str) -> None:
    assert _path_of(new).is_file() or Path(*new.split(".")).is_dir()


def test_every_shim_on_disk_is_in_the_registry() -> None:
    known = set(MODULE_SHIMS)
    strays: list[str] = []
    for package in PACKAGE_SHIMS:
        root = Path(*package.split("."))
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            text = path.as_posix()
            if "__pycache__" in text or "/tests/" in text or path.name == "__init__.py":
                continue
            dotted = ".".join(path.with_suffix("").parts)
            if dotted not in known:
                strays.append(dotted)
    assert not strays, f"шимы вне реестра: {sorted(strays)}"


@pytest.mark.parametrize("old,new", sorted(MODULE_SHIMS.items()))
def test_a_shim_only_re_exports_and_never_defines(old: str, new: str) -> None:
    tree = ast.parse(_path_of(old).read_text(encoding="utf-8"))
    defined = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    assert not defined, f"шим {old} объявляет {defined}, а должен только реэкспортировать"


@pytest.mark.parametrize("old,new", sorted(MODULE_SHIMS.items()))
def test_a_shim_names_its_symbols_explicitly(old: str, new: str) -> None:
    tree = ast.parse(_path_of(old).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert alias.name != "*", f"шим {old} использует import *"


@pytest.mark.parametrize("dotted", sorted(EXTERNAL_ENTRYPOINTS))
def test_external_entrypoints_stay_importable_until_wave_three(dotted: str) -> None:
    module = importlib.import_module(dotted)

    assert hasattr(module, "main"), f"{dotted} перестал быть точкой входа"


@pytest.mark.parametrize("dotted", sorted(EXTERNAL_ENTRYPOINTS))
def test_external_entrypoints_are_runnable_as_modules(dotted: str) -> None:
    source = _path_of(dotted).read_text(encoding="utf-8")

    assert '__name__ == "__main__"' in source, f"{dotted} нельзя запустить python -m"


@pytest.mark.parametrize("package", PACKAGE_SHIMS)
def test_package_shims_still_import(package: str) -> None:
    assert importlib.import_module(package) is not None
