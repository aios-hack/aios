from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .paths import (
    chdd_python_dir,
    docs_root,
    example_input_xlsx,
    model_z_schedule,
    normatives_xlsx,
)

APP_ROOT = Path("/app")

EXPECTED_PACKAGES = (
    ("contracts", "общие типы, интегратор"),
    ("schedule", "расписание, Савелий"),
    ("economics", "ЧДД, Савелий"),
    ("bridge", "мост к симулятору, Андрей"),
    ("surrogate", "суррогат, Андрей"),
    ("optimizer", "оптимизатор, Андрей"),
    ("connectivity", "связность, Иван"),
    ("policy", "политики, Иван"),
    ("robustness", "устойчивость, Иван"),
    ("config", "конфигурация, Иван"),
    ("ui", "интерфейс, Михаил"),
    ("llm", "слой интерпретируемости, Михаил"),
)


def _mark(present: bool) -> str:
    return "есть" if present else "НЕТ"


def _is_real_package(root: Path, name: str) -> bool:
    """Пустой каталог Python считает namespace-пакетом — это ложное «есть».

    Признаком наличия пакета берётся файл с кодом, а не импортируемость.
    """
    directory = root / name
    if directory.is_dir() and any(directory.glob("*.py")):
        return True
    spec = importlib.util.find_spec(name)
    return spec is not None and spec.origin is not None


def main(argv: list[str] | None = None) -> int:
    root = APP_ROOT if APP_ROOT.is_dir() else Path(__file__).resolve().parents[1]

    print(f"python:  {sys.version.split()[0]}")
    print(f"корень:  {root}")

    print("\nПакеты репозитория:")
    missing_packages: list[str] = []
    for name, owner in EXPECTED_PACKAGES:
        if not _is_real_package(root, name):
            missing_packages.append(name)
            print(f"  {name:<13} {_mark(False):<4}  {owner}")
        else:
            print(f"  {name:<13} {_mark(True):<4}  {owner}")

    frontend = root / "frontend" / "dist"
    print(f"\nСобранный фронт frontend/dist: {_mark(frontend.is_dir())}")

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

    if missing_packages:
        print(
            "\nОтсутствуют пакеты: "
            + ", ".join(missing_packages)
            + ".\nЭто ожидаемо, если образ собран с ветки, куда ещё не влиты "
            "чужие пакеты.\nКоманды, которым эти пакеты нужны, откажутся работать явно."
        )
    if root_docs is None:
        print(
            "\nДанные организаторов не смонтированы: расчёт ЧДД и эмит расписания "
            "недоступны.\nСмонтируйте каталог docs: -v /путь/к/aios/docs:/data/docs:ro"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
