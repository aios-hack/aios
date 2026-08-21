from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Sequence

import pytest

from aios_backend.core.contracts import IntervalResponse, StateAtDate
from aios_backend.infrastructure.llm.diagnostics import (
    Finding,
    PATTERNS,
    Thresholds,
    build_diagnosis_prompt,
    detect_all,
    detect_injection_response_lag,
    detect_injection_without_response,
    detect_liquid_jump_flat_oil,
    detect_oil_rise_without_liquid,
    detect_pressure_drop_at_high_rates,
    detect_wct_rise_without_oil,
    diagnose,
)
from aios_backend.infrastructure.llm.tests.conftest import (
    INJECTOR,
    PRODUCER,
    PRODUCER_TWO,
    make_interval_rows,
    make_state_rows,
)

N_STEPS = 6

THRESHOLDS = Thresholds(
    injection_delta_min=1500.0,
    lag_oil_delta_min=200.0,
    max_lag_steps=3,
    wct_delta_min=0.2,
    oil_delta_max=50.0,
    liquid_delta_min=500.0,
    oil_delta_abs_max=30.0,
    bhp_drop_min=20.0,
    liquid_rate_min=60.0,
    injection_volume_min=12000.0,
    window_steps=3,
    oil_delta_min=200.0,
    liquid_delta_max=50.0,
)


def flat(value: float) -> list[float]:
    return [value] * N_STEPS


def clean_intervals() -> list[IntervalResponse]:
    rows: list[IntervalResponse] = []
    rows += make_interval_rows(INJECTOR, flat(0.0), flat(0.0), flat(1000.0))
    rows += make_interval_rows(PRODUCER, flat(600.0), flat(2000.0), flat(0.0))
    rows += make_interval_rows(PRODUCER_TWO, flat(500.0), flat(1800.0), flat(0.0))
    return rows


def clean_watercut() -> dict[tuple[int, str], float]:
    return {
        (step, well): 0.7
        for step in range(N_STEPS)
        for well in (PRODUCER, PRODUCER_TWO)
    }


def clean_states() -> list[StateAtDate]:
    return make_state_rows(PRODUCER, [90.0] * 4, [120.0] * 4)


def watercut_with(series: Sequence[float]) -> dict[tuple[int, str], float]:
    result = clean_watercut()
    for step, value in enumerate(series):
        result[(step, PRODUCER)] = value
    return result


def test_injection_response_lag_found_and_clean(schedule) -> None:
    rows: list[IntervalResponse] = []
    rows += make_interval_rows(
        INJECTOR, flat(0.0), flat(0.0), [1000.0, 1000.0, 3000.0, 3000.0, 3000.0, 3000.0]
    )
    rows += make_interval_rows(
        PRODUCER, [600.0, 600.0, 600.0, 600.0, 900.0, 900.0], flat(2000.0), flat(0.0)
    )
    rows += make_interval_rows(PRODUCER_TWO, flat(500.0), flat(1800.0), flat(0.0))
    findings = detect_injection_response_lag(rows, schedule, 1500.0, 200.0, 3)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.pattern_id == "injection_response_lag"
    assert finding.well == INJECTOR
    assert finding.control_step == 2
    assert finding.inputs["lag_steps"] == 2.0
    assert finding.inputs["injection_delta"] == 2000.0
    assert finding.inputs["oil_delta"] == 300.0
    assert detect_injection_response_lag(clean_intervals(), schedule, 1500.0, 200.0, 3) == []


def test_wct_rise_without_oil_found_and_clean(schedule) -> None:
    watercut = watercut_with([0.5, 0.5, 0.5, 0.8, 0.8, 0.8])
    findings = detect_wct_rise_without_oil(
        clean_intervals(), schedule, watercut, 0.2, 50.0
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding.pattern_id == "wct_rise_without_oil"
    assert finding.well == PRODUCER
    assert finding.control_step == 3
    assert finding.inputs == {
        "watercut_prev": 0.5,
        "watercut_curr": 0.8,
        "oil_delta": 0.0,
    }
    assert (
        detect_wct_rise_without_oil(
            clean_intervals(), schedule, clean_watercut(), 0.2, 50.0
        )
        == []
    )


def test_liquid_jump_flat_oil_found_and_clean(schedule) -> None:
    rows: list[IntervalResponse] = []
    rows += make_interval_rows(INJECTOR, flat(0.0), flat(0.0), flat(1000.0))
    rows += make_interval_rows(
        PRODUCER,
        flat(600.0),
        [2000.0, 2000.0, 2000.0, 2600.0, 2600.0, 2600.0],
        flat(0.0),
    )
    rows += make_interval_rows(PRODUCER_TWO, flat(500.0), flat(1800.0), flat(0.0))
    watercut = watercut_with([0.5, 0.5, 0.5, 0.75, 0.75, 0.75])
    findings = detect_liquid_jump_flat_oil(rows, schedule, watercut, 500.0, 30.0, 0.1)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.pattern_id == "liquid_jump_flat_oil"
    assert finding.well == PRODUCER
    assert finding.control_step == 3
    assert finding.inputs["liquid_delta"] == 600.0
    assert (
        detect_liquid_jump_flat_oil(
            clean_intervals(), schedule, clean_watercut(), 500.0, 30.0, 0.1
        )
        == []
    )


def test_pressure_drop_at_high_rates_found_and_clean() -> None:
    states = make_state_rows(PRODUCER, [90.0] * 4, [120.0, 120.0, 95.0, 95.0])
    findings = detect_pressure_drop_at_high_rates(states, 20.0, 60.0)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.pattern_id == "pressure_drop_at_high_rates"
    assert finding.well == PRODUCER
    assert finding.window == (1, 2)
    assert finding.inputs == {
        "bhp_prev": 120.0,
        "bhp_curr": 95.0,
        "liquid_rate": 90.0,
    }
    assert detect_pressure_drop_at_high_rates(clean_states(), 20.0, 60.0) == []


def test_injection_without_response_found_and_clean(schedule) -> None:
    rows: list[IntervalResponse] = []
    rows += make_interval_rows(INJECTOR, flat(0.0), flat(0.0), flat(5000.0))
    rows += make_interval_rows(PRODUCER, flat(600.0), flat(2000.0), flat(0.0))
    rows += make_interval_rows(PRODUCER_TWO, flat(500.0), flat(1800.0), flat(0.0))
    findings = detect_injection_without_response(rows, schedule, 12000.0, 50.0, 3)
    assert findings
    finding = findings[0]
    assert finding.pattern_id == "injection_without_response"
    assert finding.well == INJECTOR
    assert finding.window == (0, 2)
    assert finding.inputs == {"injection_total": 15000.0, "oil_delta": 0.0}
    assert (
        detect_injection_without_response(clean_intervals(), schedule, 12000.0, 50.0, 3)
        == []
    )


def test_oil_rise_without_liquid_found_and_clean(schedule) -> None:
    rows: list[IntervalResponse] = []
    rows += make_interval_rows(INJECTOR, flat(0.0), flat(0.0), flat(1000.0))
    rows += make_interval_rows(
        PRODUCER,
        [600.0, 600.0, 900.0, 900.0, 900.0, 900.0],
        flat(2000.0),
        flat(0.0),
    )
    rows += make_interval_rows(PRODUCER_TWO, flat(500.0), flat(1800.0), flat(0.0))
    findings = detect_oil_rise_without_liquid(rows, schedule, 200.0, 50.0)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.pattern_id == "oil_rise_without_liquid"
    assert finding.well == PRODUCER
    assert finding.control_step == 2
    assert finding.severity == "info"
    assert (
        detect_oil_rise_without_liquid(clean_intervals(), schedule, 200.0, 50.0) == []
    )


def test_detect_all_clean_is_empty(schedule) -> None:
    findings = detect_all(
        clean_states(), clean_intervals(), schedule, clean_watercut(), THRESHOLDS
    )
    assert findings == []


def test_detect_all_finds_pattern(schedule) -> None:
    rows: list[IntervalResponse] = []
    rows += make_interval_rows(
        INJECTOR, flat(0.0), flat(0.0), [1000.0, 1000.0, 3000.0, 3000.0, 3000.0, 3000.0]
    )
    rows += make_interval_rows(
        PRODUCER, [600.0, 600.0, 600.0, 600.0, 900.0, 900.0], flat(2000.0), flat(0.0)
    )
    rows += make_interval_rows(PRODUCER_TWO, flat(500.0), flat(1800.0), flat(0.0))
    findings = detect_all(clean_states(), rows, schedule, clean_watercut(), THRESHOLDS)
    assert "injection_response_lag" in {f.pattern_id for f in findings}


def test_all_customer_patterns_registered() -> None:
    assert set(PATTERNS) == {
        "injection_response_lag",
        "wct_rise_without_oil",
        "liquid_jump_flat_oil",
        "pressure_drop_at_high_rates",
        "injection_without_response",
        "oil_rise_without_liquid",
    }


def _sample_findings(schedule) -> list[Finding]:
    watercut = watercut_with([0.5, 0.5, 0.5, 0.8, 0.8, 0.8])
    return detect_wct_rise_without_oil(
        clean_intervals(), schedule, watercut, 0.2, 50.0
    )


def test_prompt_contains_all_finding_numbers(schedule) -> None:
    findings = _sample_findings(schedule)
    prompt = build_diagnosis_prompt(findings)
    for finding in findings:
        assert finding.name_ru in prompt
        assert finding.well in prompt
        for value in finding.inputs.values():
            assert str(value) in prompt


def test_prompt_has_no_invented_numbers(schedule) -> None:
    findings = _sample_findings(schedule)
    prompt = build_diagnosis_prompt(findings)
    allowed: set[str] = set()
    for finding in findings:
        for value in finding.inputs.values():
            allowed.update(re.findall(r"\d+(?:\.\d+)?", str(value)))
        if finding.control_step is not None:
            allowed.add(str(finding.control_step))
        if finding.window is not None:
            allowed.add(str(finding.window[0]))
            allowed.add(str(finding.window[1]))
    tokens = set(re.findall(r"\d+(?:\.\d+)?", prompt))
    assert tokens <= allowed


def test_prompt_requires_findings() -> None:
    with pytest.raises(ValueError):
        build_diagnosis_prompt([])


def test_findings_json_serializable(schedule) -> None:
    findings = _sample_findings(schedule)
    payload = json.dumps([asdict(f) for f in findings], ensure_ascii=False)
    restored = json.loads(payload)
    assert restored[0]["pattern_id"] == "wct_rise_without_oil"
    assert restored[0]["inputs"]["watercut_curr"] == 0.8


class _FakeClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "текст диагноза"


def test_diagnose_sends_prompt_and_returns_text(schedule) -> None:
    findings = _sample_findings(schedule)
    client = _FakeClient()
    assert diagnose(findings, client) == "текст диагноза"
    assert client.prompts == [build_diagnosis_prompt(findings)]
