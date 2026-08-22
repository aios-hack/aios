"""Lint file paths referenced in backtick spans across tracked markdown.

Motivation: after the 22.08 move of code into ``backend/`` the docs kept
referencing removed top-level packages (``contracts/``, ``bridge/``, ``ui/``,
``aios_cli/``) — over fifty dead links found only by reading everything by
hand. This test catches that class of drift automatically.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

PATH_PATTERN = re.compile(r"`([^`\n]+\.(?:py|ts|tsx|json|sh|inc|md))`")

# aios и docs — независимые репозитории, клонируются по отдельности; тест,
# проверяющий ссылки между ними, будет падать у того, у кого нет сиблинга
# (см. D1 "Что не делать" в docs/v2/tasks/docs.md).
CROSS_REPO_PREFIXES = ("docs/", "../docs/", "../../docs/")

# Каталоги, которые правит не интегратор — интегратор не редактирует чужие
# файлы даже ради починки мёртвой ссылки (CLAUDE.md, правило №2). Уборка
# frontend/*.md — отдельная задача D7, её владелец Михаил.
EXCLUDED_FILE_PREFIXES = ("frontend/",)

# UI-экспорт описывает целевую структуру фронтенда для будущей реализации:
# пути вида `src/theme/tokens.ts`, `Slider/Slider.tsx` — ориентиры для
# команды фронтенда, а не буквальные существующие файлы на момент написания.
EXCLUDED_FILES = {
    "backend/presentation/ui_export/CONVENTIONS.md",
    "backend/presentation/ui_export/GRAPH.md",
}

# Точечные исключения: (файл, путь) -> обоснование.
EXPLICIT_EXCLUSIONS: dict[tuple[str, str], str] = {
    (
        "SURROGATE-REQUESTS-20.08.md",
        "dataset-700/model-task34-700/training_report.json",
    ): "dataset-700 — отдельный репозиторий aios-hack/dataset-700 (см. README §8), не часть aios",
    (
        "README.md",
        "public/data/demo-script.json",
    ): "путь внутри frontend/public/, генерируется отдельной командой; в git и в образе отсутствует (README §9)",
}


def _is_excluded_path(path: str) -> bool:
    if "/" not in path:
        # Голое имя файла без каталога — упоминание в прозе, не путь.
        return True
    if path.startswith(CROSS_REPO_PREFIXES):
        return True
    if "<" in path or "*" in path:
        return True
    if path.startswith("/") or path.startswith("w:"):
        return True
    return False


def tracked_markdown_files(root: Path) -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [root / line for line in output.splitlines() if line]


def find_broken_links(root: Path, md_files: list[Path]) -> list[tuple[str, int, str]]:
    """Return (relative file, line number, missing path) for each dead link."""
    broken: list[tuple[str, int, str]] = []
    for md_file in md_files:
        relative = str(md_file.relative_to(root))
        if relative.startswith(EXCLUDED_FILE_PREFIXES) or relative in EXCLUDED_FILES:
            continue
        for lineno, line in enumerate(md_file.read_text(encoding="utf-8").splitlines(), 1):
            for match in PATH_PATTERN.finditer(line):
                candidate = match.group(1)
                if _is_excluded_path(candidate):
                    continue
                if (relative, candidate) in EXPLICIT_EXCLUSIONS:
                    continue
                resolved_from_root = (root / candidate).exists()
                resolved_from_file_dir = (md_file.parent / candidate).exists()
                if not resolved_from_root and not resolved_from_file_dir:
                    broken.append((relative, lineno, candidate))
    return broken


def test_no_broken_markdown_links() -> None:
    md_files = tracked_markdown_files(REPO_ROOT)
    assert md_files, "не нашлось ни одного отслеживаемого .md файла"
    broken = find_broken_links(REPO_ROOT, md_files)
    assert not broken, "мёртвые ссылки на файлы:\n" + "\n".join(
        f"{file}:{line}: `{path}`" for file, line, path in broken
    )


def test_broken_link_is_detected(tmp_path: Path) -> None:
    (tmp_path / "existing.py").write_text("", encoding="utf-8")
    doc = tmp_path / "NOTE.md"
    doc.write_text(
        "рабочая ссылка `existing.py`\n"
        "сломанная ссылка `pkg/missing_module.py` во второй строке\n",
        encoding="utf-8",
    )

    broken = find_broken_links(tmp_path, [doc])

    assert broken == [("NOTE.md", 2, "pkg/missing_module.py")]
