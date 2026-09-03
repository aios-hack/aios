from __future__ import annotations

from backend.application.jarvis.guard import (
    collect_numbers,
    guard_caption,
    unsupported_numbers,
)

PAYLOADS = [
    {
        "npv": 1161713780.758579,
        "watercut": 0.96,
        "rows": [{"well": "13", "value": -20491675.0}],
        "active_wells": 96,
    },
    {"total": 11873122324.910866, "share": 0.097844},
]


def test_number_from_tool_passes_verbatim() -> None:
    result = guard_caption("Вклад правила R0 — 1 161 713 781 руб.", PAYLOADS)
    assert result.ok is True
    assert result.dropped == ()
    assert "1 161 713 781" in result.text


def test_percent_form_of_a_fraction_passes() -> None:
    result = guard_caption("Обводнённость дошла до 96 %.", PAYLOADS)
    assert result.ok is True


def test_rounded_number_passes_within_two_significant_digits() -> None:
    result = guard_caption("Итог по фонду — 11,9 млрд руб.", PAYLOADS)
    assert result.ok is True


def test_invented_number_is_cut() -> None:
    result = guard_caption("Скважина дала 777 555 руб. дохода.", PAYLOADS)
    assert result.ok is False
    assert result.dropped == ("777 555",)
    assert "777 555" not in result.text


def test_dates_are_not_treated_as_numbers() -> None:
    text = "Скважину закрыли в марте 2013 года, а ввели 2007-01-01."
    assert unsupported_numbers(text, collect_numbers(PAYLOADS)) == []


def test_iso_date_alone_is_not_a_number() -> None:
    assert unsupported_numbers("Шаг 2015-01-01.", []) == []


def test_rule_code_is_not_a_number() -> None:
    assert unsupported_numbers("Сработало правило R0 и правило R3.", []) == []


def test_well_number_is_not_a_measurement() -> None:
    assert unsupported_numbers("Скважина 45 закрыта.", []) == []


def test_decimal_comma_is_understood() -> None:
    result = guard_caption("Доля правила — 0,098 от итога.", PAYLOADS)
    assert result.ok is True


def test_negative_value_from_tool_passes() -> None:
    result = guard_caption("Скважина принесла −20 491 675 руб.", PAYLOADS)
    assert result.ok is True


def test_several_invented_numbers_all_cut() -> None:
    result = guard_caption("Было 5555 и стало 6666.", PAYLOADS)
    assert result.ok is False
    assert set(result.dropped) == {"5555", "6666"}


def test_caption_without_numbers_passes() -> None:
    result = guard_caption("Скважина перестала окупать содержание.", [])
    assert result.ok is True
    assert result.text == "Скважина перестала окупать содержание."


def test_collect_numbers_walks_nested_structures() -> None:
    found = collect_numbers({"a": [{"b": 7.0}], "c": {"d": [1, 2]}})
    assert 7.0 in found
    assert 1.0 in found
    assert 2.0 in found


def test_booleans_are_not_numbers() -> None:
    assert collect_numbers({"flag": True}) == set()
