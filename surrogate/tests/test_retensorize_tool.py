from __future__ import annotations

from types import SimpleNamespace

from tools.surrogate_retensorize import _canonical_buckets


def _material(scenario_id: str):
    return SimpleNamespace(spec=SimpleNamespace(scenario_id=scenario_id))


def test_canonical_buckets_do_not_depend_on_materialization_order() -> None:
    canonical = [
        *(('dataset-main', _material(f"pilot-{index:04d}")) for index in range(200)),
        *(
            ('dataset-extra-500', _material(f"extra-{index:04d}"))
            for index in range(500)
        ),
    ]
    scrambled = canonical[::2] + canonical[1::2]

    first = _canonical_buckets(canonical, 20260817)
    second = _canonical_buckets(scrambled, 20260817)

    assert first == second
    assert list(first.values()).count("train") == 490
    assert list(first.values()).count("validation") == 105
    assert list(first.values()).count("test") == 105
