from __future__ import annotations

from typing import Any

from backend.shared.i18n.catalog import DEFAULT_LANG, translate


def notice_fields(key: str, lang: str = DEFAULT_LANG, **params: Any) -> dict[str, str]:
    return {"notice": translate(key, lang, **params), "notice_key": key}


def apply_notice(
    meta: dict[str, Any], key: str, lang: str = DEFAULT_LANG, **params: Any
) -> dict[str, Any]:
    meta.update(notice_fields(key, lang, **params))
    return meta


__all__ = ["apply_notice", "notice_fields"]
