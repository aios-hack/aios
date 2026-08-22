"""Report whether this checkout or image has the things it can use."""

from __future__ import annotations

import importlib.util
import shutil
import sys

from backend.core.paths import project_root

from .paths import (
    chdd_python_dir,
    docs_root,
    example_input_xlsx,
    model_z_schedule,
    normatives_xlsx,
)


CLI_MODULES = (
    "backend.presentation.cli.npv",
    "backend.presentation.cli.emit",
    "backend.presentation.cli.web",
    "backend.presentation.cli.run",
)
OPTIONAL_DEPENDENCIES = ("anthropic", "numpy", "torch")


def _mark(present: bool) -> str:
    return "есть" if present else "НЕТ"


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def main(argv: list[str] | None = None) -> int:
    del argv
    root = project_root()
    print(f"python:  {sys.version.split()[0]}")
    print(f"корень:  {root}")

    print("\nКоманды backend:")
    for module in CLI_MODULES:
        print(f"  {module:<36} {_mark(_module_available(module))}")

    frontend = root / "frontend" / "dist"
    print(f"\nСобранный фронт frontend/dist: {_mark(frontend.is_dir())}")
    print(f"Docker для OPM smoke:           {_mark(shutil.which('docker') is not None)}")

    print("\nОпциональные зависимости:")
    for name in OPTIONAL_DEPENDENCIES:
        print(f"  {name:<33} {_mark(_module_available(name))}")

    print("\nДанные организаторов (монтируются снаружи, в образ не входят):")
    root_docs = docs_root()
    print(f"  каталог docs             {_mark(root_docs is not None)}  {root_docs or ''}")
    for label, path in (
        ("дек Model_Z_sch.inc", model_z_schedule()),
        ("расчётчик CHDD_PYTHON", chdd_python_dir()),
        ("Нормативы_ЧДД.xlsx", normatives_xlsx()),
        ("Пример_исходных_данных", example_input_xlsx()),
    ):
        print(f"  {label:<25}{_mark(path is not None)}  {path or ''}")

    if root_docs is None:
        print(
            "\nДанные организаторов не смонтированы: это нормально для чистого "
            "образа. Для расчёта смонтируйте docs в /data/docs:ro."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
