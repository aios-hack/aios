from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from backend.contexts.assistant.application.tools.context import Card, ToolContext, ToolFailure
from backend.shared.settings import Settings
from backend.shared.paths import repository_root

CONFIG_ENV_VAR = "AIOS_JARVIS_CONFIG"
COMPETITION_FILE = "competition-constraints.json"
CASES_DIR = "cases"
PROVENANCE = "config"
DEFAULT_CASE = "competition"
SOURCE_SUFFIX = "_source"
UNITS: Mapping[str, str] = {
    "water_reinjection_fraction": "fraction",
    "water_reinjection_lag_steps": "steps",
    "external_water_m3_per_day": "m3/day",
    "bhp_producer_min_bar": "bar",
    "bhp_injector_max_bar": "bar",
    "compensation_min": "fraction",
    "compensation_max": "fraction",
}
GROUPS: tuple[str, ...] = (
    "injection_limits",
    "liquid_limits",
    "production_floors",
    "oil_limits",
    "watercut_limits",
    "well_outages",
)
TITLES: Mapping[str, Mapping[str, str]] = {
    "constraints": {"ru": "Ограничения кейса {case}", "en": "Constraints of case {case}"}
}


def _repository_root() -> Path:
    return repository_root(Path.cwd())


def _config_root(settings: Settings | None = None) -> Path:
    resolved = Settings.from_env() if settings is None else settings
    if resolved.jarvis_config is not None:
        return resolved.jarvis_config
    return _repository_root() / "config"


def _read(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise ToolFailure(
            f"файла ограничений {path} нет: набор ограничений не задан, а "
            "выдумывать лимиты нельзя"
        )
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise ToolFailure(
            f"файл ограничений {path} не читается: {error}"
        ) from error
    if not isinstance(loaded, dict):
        raise ToolFailure(f"файл ограничений {path} не объект JSON")
    return loaded


def _cases(root: Path) -> tuple[str, ...]:
    folder = root / CASES_DIR
    if not folder.is_dir():
        return ()
    return tuple(sorted(path.stem for path in folder.glob("*.json")))


def _items(loaded: Mapping[str, Any], source: str) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    infrastructure = loaded.get("infrastructure") or {}
    for key, value in infrastructure.items():
        if key.endswith(SOURCE_SUFFIX):
            continue
        collected.append(
            {
                "key": key,
                "value": value,
                "unit": UNITS.get(key),
                "source": infrastructure.get(f"{key}{SOURCE_SUFFIX}") or source,
                "group": "infrastructure",
            }
        )
    for name in GROUPS:
        entry = loaded.get(name)
        if entry is None:
            continue
        size = len(entry) if isinstance(entry, (list, tuple, dict)) else None
        collected.append(
            {
                "key": name,
                "value": size,
                "unit": "records",
                "source": source,
                "group": "limits",
                "empty": size == 0,
            }
        )
    return collected


def case_constraints(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    root = _config_root()
    requested = arguments.get("case")
    known = _cases(root)
    if requested is None or str(requested) == DEFAULT_CASE:
        name = DEFAULT_CASE
        path = root / COMPETITION_FILE
    else:
        name = str(requested)
        if name not in known:
            listed = ", ".join((DEFAULT_CASE, *known))
            raise ToolFailure(
                f"кейса {name!r} нет в {root / CASES_DIR}: известные кейсы — "
                f"{listed}"
            )
        path = root / CASES_DIR / f"{name}.json"
    loaded = _read(path)
    items = _items(loaded, str(path.name))
    payload = {
        "case": name,
        "items": items,
        "known_cases": [DEFAULT_CASE, *known],
        "source": str(path),
    }
    entry = TITLES["constraints"]
    return Card(
        type="constraints",
        title=entry.get(context.lang, entry["ru"]).format(case=name),
        payload=payload,
        provenance=PROVENANCE,
    )
