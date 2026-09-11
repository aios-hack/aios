from __future__ import annotations

from typing import Any

from backend.shared.i18n.catalog import DEFAULT_LANG, SUPPORTED_LANGS, translate

LEGACY_FIELDS: dict[str, str] = {lang: f"notice_{lang}" for lang in SUPPORTED_LANGS}


def notice_fields(key: str, lang: str = DEFAULT_LANG, **params: Any) -> dict[str, str]:
    fields: dict[str, str] = {
        "notice": translate(key, lang, **params),
        "notice_key": key,
    }
    for language, field in LEGACY_FIELDS.items():
        fields[field] = translate(key, language, **params)
    return fields


def apply_notice(
    meta: dict[str, Any], key: str, lang: str = DEFAULT_LANG, **params: Any
) -> dict[str, Any]:
    meta.update(notice_fields(key, lang, **params))
    return meta


__all__ = ["LEGACY_FIELDS", "apply_notice", "notice_fields"]
