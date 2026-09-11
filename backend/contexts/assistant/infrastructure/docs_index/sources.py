from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.contexts.assistant.domain.errors import DocsIndexError
from backend.contexts.assistant.infrastructure.docs_index.models import Stamp
from backend.shared.settings import Settings


DOCS_ENV_VAR = "AIOS_JARVIS_DOCS"


OUT_ENV_VAR = "AIOS_OUT_DIR"


CACHE_NAME = "docs-index.json"


ROOT_MARKDOWN_LIMIT = 40


def repository_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise DocsIndexError(
        "repository root not found: no pyproject.toml in any parent "
        f"directory of {here}"
    )


def default_cache_path(settings: Settings | None = None) -> Path:
    resolved = Settings.from_env() if settings is None else settings
    base = resolved.out_root if resolved.raw.get(OUT_ENV_VAR) else repository_root() / "out"
    return base / "jarvis" / CACHE_NAME


def default_roots() -> tuple[Path, ...]:
    from_env = Settings.from_env().raw.get(DOCS_ENV_VAR)
    if from_env:
        return tuple(
            Path(part.strip()) for part in from_env.split(";") if part.strip()
        )
    root = repository_root()
    found = [root]
    external = root.parent / "docs"
    if external.is_dir():
        found.append(external)
    return tuple(found)


def relative_source(path: Path, roots: Sequence[Path]) -> str:
    for root in roots:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            continue
    return path.name


def walk_documents(roots: Sequence[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.md"))[:ROOT_MARKDOWN_LIMIT]:
            if path not in seen:
                seen.add(path)
                found.append(path)
        readme = root / "config" / "README.md"
        if readme.is_file() and readme not in seen:
            seen.add(readme)
            found.append(readme)
        checkpoints = root / "checkpoints"
        if checkpoints.is_dir():
            for path in sorted(checkpoints.glob("*.md")):
                if path not in seen:
                    seen.add(path)
                    found.append(path)
        for path in sorted(root.glob("*.txt")):
            if path not in seen:
                seen.add(path)
                found.append(path)
    return found


def resolve_knowledge_root(roots: Sequence[Path], given: Path | None) -> Path | None:
    if given is not None:
        return given if given.is_dir() else None
    for root in roots:
        candidate = root / "frontend" / "public" / "jarvis" / "knowledge"
        if candidate.is_dir():
            return candidate
    return None


def _stamp_of(path: Path) -> Stamp:
    info = path.stat()
    return Stamp(path=str(path), mtime=info.st_mtime, size=info.st_size)


def collect_stamps(roots: Sequence[Path], knowledge: Path | None) -> list[Stamp]:
    collected = [_stamp_of(path) for path in walk_documents(roots) if path.is_file()]
    if knowledge is not None:
        for name in ("glossary.json", "guide.json"):
            path = knowledge / name
            if path.is_file():
                collected.append(_stamp_of(path))
    return collected


def stamps_match(
    stored: Sequence[Mapping[str, Any]], fresh: Sequence[Stamp]
) -> bool:
    if len(stored) != len(fresh):
        return False
    left = {
        str(item.get("path")): (
            float(item.get("mtime", 0.0)),
            int(item.get("size", 0)),
        )
        for item in stored
    }
    right = {stamp.path: (stamp.mtime, stamp.size) for stamp in fresh}
    return left == right
