from __future__ import annotations

from backend.application.jarvis.fixtures import Recording
from backend.application.jarvis.tools.context import ConsoleContext

STEP_2015 = 96
STEP_R1_FIRED = 10
YEAR_2015_FROM = 96
YEAR_2015_TO = 107

WHY_WELL_CLOSED = Recording(
    name="why-well-13",
    question="Почему скважина 13 так работает?",
    console=ConsoleContext(
        scenario="whatif-injection-cut",
        step=STEP_R1_FIRED,
        date="2007-11-01",
        selected_well="13",
        workspace="decisions",
        view="rules",
    ),
    calls=(
        {"name": "well_snapshot", "args": {"well": "13", "step": STEP_R1_FIRED}},
        {
            "name": "well_series",
            "args": {
                "well": "13",
                "metric": "watercut",
                "from_step": 0,
                "to_step": STEP_R1_FIRED,
                "window": [4, STEP_R1_FIRED],
            },
        },
        {
            "name": "explain_decision",
            "args": {"well": "13", "step": STEP_R1_FIRED},
        },
    ),
    caption=(
        "Скважина 13 держится на правиле R1: при обводнённости 0,614 система "
        "выставила ей уставку по жидкости, потому что закачка на этом участке "
        "ещё превращается в нефть, а не в воду."
    ),
)

WHO_DRAGS_NPV = Recording(
    name="who-drags-npv",
    question="Кто тянет ЧДД вниз?",
    console=ConsoleContext(
        scenario="base",
        step=STEP_2015,
        date="2015-01-01",
        workspace="money",
        view="rank",
    ),
    calls=(
        {"name": "rank_wells", "args": {"by": "npv", "order": "asc", "limit": 10}},
        {"name": "connectivity", "args": {"well": "76", "limit": 8}},
        {"name": "field_metrics", "args": {"step": STEP_2015}},
    ),
    caption=(
        "Итог тянут вниз десять скважин, худшая из них — 76: она работает в "
        "минус, а её соседи по матрице влияния показывают, куда уходит закачка."
    ),
)

FIELD_IN_2015 = Recording(
    name="field-in-2015",
    question="Что случилось с фондом в 2015 году?",
    console=ConsoleContext(
        scenario="base",
        step=STEP_2015,
        date="2015-01-01",
        workspace="history",
        view="matrix",
    ),
    calls=(
        {
            "name": "field_events",
            "args": {"from_step": YEAR_2015_FROM, "to_step": YEAR_2015_TO},
        },
        {"name": "field_metrics", "args": {"step": STEP_2015}},
        {"name": "well_snapshot", "args": {"well": "72", "step": 102}},
    ),
    caption=(
        "За 2015 год фонд пополнился одной скважиной — 72 введена в июле; "
        "остальной год фонд отработал без вводов, переводов и остановок."
    ),
)

COMPARE_SCENARIOS = Recording(
    name="compare-scenarios",
    question="Сравни base и whatif-injection-cut",
    console=ConsoleContext(
        scenario="base",
        step=STEP_2015,
        date="2015-01-01",
        workspace="money",
        view="comparison",
    ),
    calls=(
        {
            "name": "compare_scenarios",
            "args": {"a": "base", "b": "whatif-injection-cut"},
        },
        {"name": "rule_impact", "args": {}},
    ),
    caption=(
        "Срезанная закачка меняет итог по методике и перераспределяет вклад по "
        "скважинам; сильнее всего расходятся те, кто стоял ближе к нагнетанию."
    ),
)

WHAT_IS_NPV = Recording(
    name="what-is-npv",
    question="Что такое ЧДД?",
    console=ConsoleContext(
        scenario="base",
        step=223,
        date="2025-08-01",
        workspace="overview",
        view="fund",
    ),
    calls=(
        {"name": "explain_term", "args": {"query": "ЧДД", "lang": "ru"}},
        {"name": "field_metrics", "args": {"step": 223}},
        {
            "name": "platform_guide",
            "args": {"workspace": "money", "view": "rank", "lang": "ru"},
        },
    ),
    caption=(
        "ЧДД — дисконтированная разница выручки и затрат за весь горизонт; итог "
        "по сценарию рядом, а разложение по скважинам живёт на «Деньгах»."
    ),
)

WHERE_IS_CONNECTIVITY = Recording(
    name="where-is-connectivity",
    question="Где посмотреть, кто с кем связан?",
    console=ConsoleContext(
        scenario="base",
        step=STEP_2015,
        date="2015-01-01",
        selected_well="13",
        workspace="overview",
        view="fund",
    ),
    calls=(
        {
            "name": "platform_guide",
            "args": {"workspace": "field", "view": "projection", "lang": "ru"},
        },
        {"name": "connectivity", "args": {"well": "13", "limit": 6}},
    ),
    caption=(
        "Связи живут на «Поле → Проекция»: узлы — скважины, рёбра — измеренное "
        "влияние закачки, а ползунок λ убирает слабые связи с карты."
    ),
)

RECORDINGS: tuple[Recording, ...] = (
    WHY_WELL_CLOSED,
    WHO_DRAGS_NPV,
    FIELD_IN_2015,
    COMPARE_SCENARIOS,
    WHAT_IS_NPV,
    WHERE_IS_CONNECTIVITY,
)
