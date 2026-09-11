from __future__ import annotations

import pytest

from backend.shared.errors import NotFoundError
from backend.shared.i18n import MESSAGES, SUPPORTED_LANGS, Messages, translate


def test_both_languages_are_present() -> None:
    assert set(MESSAGES.languages) == set(SUPPORTED_LANGS)


def test_key_parity_between_languages() -> None:
    assert MESSAGES.keys("ru") == MESSAGES.keys("en")


def test_no_catalog_value_is_empty() -> None:
    for lang in SUPPORTED_LANGS:
        for key in MESSAGES.keys(lang):
            assert MESSAGES.get(key, lang).strip(), (lang, key)


def test_the_two_languages_actually_differ_for_notices() -> None:
    key = "showcase.notice.demo"

    assert MESSAGES.get(key, "ru") != MESSAGES.get(key, "en")


def test_showcase_notices_keep_the_wording_the_bundles_already_carry() -> None:
    assert MESSAGES.get("showcase.notice.demo", "ru") == (
        "Демонстрационные данные, не результат расчёта"
    )
    assert MESSAGES.get("showcase.notice.demo", "en") == (
        "Demonstration data, not a computed result"
    )
    assert MESSAGES.get("showcase.notice.real", "ru") == (
        "Настоящий расчёт: базовый прогон OPM без перекладки, эталонная методика ЧДД"
    )


def test_an_unknown_key_is_refused_not_silently_blank() -> None:
    with pytest.raises(NotFoundError) as error:
        MESSAGES.get("нет.такого.ключа")

    assert error.value.code == "i18n.key_missing"


def test_an_unknown_language_falls_back_to_russian() -> None:
    assert MESSAGES.get("showcase.notice.demo", "de") == MESSAGES.get(
        "showcase.notice.demo", "ru"
    )


def test_parameters_are_substituted() -> None:
    catalog = Messages({"ru": {"greet": "привет, {name}"}, "en": {"greet": "hello, {name}"}})

    assert catalog.get("greet", "en", name="мир") == "hello, мир"


def test_translate_is_the_module_level_shortcut() -> None:
    assert translate("showcase.notice.demo", "en") == MESSAGES.get(
        "showcase.notice.demo", "en"
    )
