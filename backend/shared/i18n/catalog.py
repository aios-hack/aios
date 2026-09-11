from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from backend.shared.errors import ConfigurationError, NotFoundError
from backend.shared.json_io import read_json

CATALOG_DIR = Path(__file__).resolve().parent
DEFAULT_LANG = "ru"
SUPPORTED_LANGS: tuple[str, ...] = ("ru", "en")


def _load(lang: str) -> Mapping[str, str]:
    path = CATALOG_DIR / f"{lang}.json"
    if not path.is_file():
        raise ConfigurationError(
            f"message catalog {lang} not found: {path}",
            code="i18n.catalog_missing",
            lang=lang,
        )
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ConfigurationError(
            f"message catalog {lang}: an object is expected",
            code="i18n.catalog_malformed",
            lang=lang,
        )
    return {str(key): str(value) for key, value in payload.items()}


class Messages:
    def __init__(self, catalogs: Mapping[str, Mapping[str, str]] | None = None) -> None:
        self._catalogs: dict[str, Mapping[str, str]] = (
            {lang: dict(items) for lang, items in catalogs.items()}
            if catalogs is not None
            else {lang: _load(lang) for lang in SUPPORTED_LANGS}
        )

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(sorted(self._catalogs))

    def keys(self, lang: str = DEFAULT_LANG) -> tuple[str, ...]:
        return tuple(sorted(self._catalogs.get(lang, {})))

    def has(self, key: str, lang: str = DEFAULT_LANG) -> bool:
        return key in self._catalogs.get(lang, {})

    def get(self, key: str, lang: str = DEFAULT_LANG, **params: Any) -> str:
        catalog = self._catalogs.get(lang)
        if catalog is None:
            catalog = self._catalogs.get(DEFAULT_LANG, {})
        template = catalog.get(key)
        if template is None:
            template = self._catalogs.get(DEFAULT_LANG, {}).get(key)
        if template is None:
            raise NotFoundError(
                f"message {key!r} is absent from the catalog", code="i18n.key_missing", key=key
            )
        if not params:
            return template
        return template.format(**params)


MESSAGES = Messages()


def translate(key: str, lang: str = DEFAULT_LANG, **params: Any) -> str:
    return MESSAGES.get(key, lang, **params)


__all__ = [
    "CATALOG_DIR",
    "DEFAULT_LANG",
    "MESSAGES",
    "Messages",
    "SUPPORTED_LANGS",
    "translate",
]
