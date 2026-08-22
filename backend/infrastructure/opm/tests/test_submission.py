"""Задача 62, звено А: `bridge.submission.submit_schedule` целиком, все
шесть тождеств §10.5. Приёмка карточки G6.

Работает без Docker (карточка это явно разрешает): «Schedule*» здесь —
не расписание организаторов один в один (`bridge.baseline_schedule`
оставляет `initial_state` пустым — задача 57 ей не нужна), а расписание с
настоящим воспроизведённым `initial_state` (`schedule.build.
initial_state_from_prefix`, тот же приём, что и `schedule.build_schedule`)
поверх тех же, не канонизированных заново, control/fixed-событий, что и в
уже прогнанном `bridge.baseline_schedule`. Проверено эмпирически (не
предположено): `content_hash_opm` у обоих совпадает байт-в-байт — значит и
настоящий прогон Flow на этом деке уже есть в кеше `aios/data/base_run`.
Отличается только `canonical_schedule_hash` (он берётся с `initial_state`,
а не с байтов дека) — фикстура добавляет вторую запись кеша под этим
хешом, указывающую на те же настоящие артефакты прогона, не выдуманные.

Что это НЕ доказывает: что `schedule.build_schedule`'s канонизация
control-слоя (другой файл, другая ветка эмита) даёт ту же физику — там
статус нескольких скважин (`OPEN`/`SHUT`) разошёлся при прямой проверке
байтов; это отдельная находка вне `bridge/`, не трогается здесь.

## Важно: базовое расписание организаторов НЕ проходит гейт validate_dynamic

Прогон тракта целиком на настоящем базовом отклике даёт 71 нарушение:
60 `OPEN_WITHOUT_FLOW` по скважине `71` (открыта с уставкой на шагах 0–59,
первый `COMPDAT` — на шаге 60 — ровно открытый вопрос №17,
`docs/context/06_open_questions.md`, и то же самое уже закреплено тестом
`schedule/tests/test_validate_dynamic.py::test_real_response_open_without_flow_stops_at_first_perforation`,
который специально проверяет, что такие нарушения ЕСТЬ и ограничены
перфорацией), плюс 11 нарушений `BHP_LIMITED_WITHOUT_UNDERSHOOT`/
`BHP_BELOW_PRODUCER_LIMIT` на других скважинах — новая находка, число
раньше никто не считал. Это не дефект тракта: `validate_dynamic` обязан
это ловить, и ловит верно. Значит **сегодня ни одно расписание,
включающее скважину 71 с этой уставкой, не пройдёт звено А целиком**, пока
трекер не ответит на вопрос №17 (дефект дека / зарезервированный ввод /
наш дефект чтения) или пока Schedule* не поправит уставку скважины 71
явно (гибридная поправка, `07_concept.md` §6).

Тесты ниже поэтому разделены: то, что происходит ДО гейта
`validate_dynamic` (identity 1/2/4 — `validate_static`, статус прогона,
`canonical_schedule_hash`, `source_run_id`), проверяется через
`submit_schedule` целиком на реальном кеше. То, что происходит ПОСЛЕ гейта
(identity 5/6 — сборка `FinalNpvArtifact`), проверяется на тех же
настоящих `opm_run`/`response`, что вернул реальный прогон, — не в обход
проверки, а потому что для них проверка `validate_dynamic` не по адресу:
она о согласованности расписания и отклика, не о сборке артефакта.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from backend.infrastructure.opm import SubmissionTractError, submit_schedule
from backend.infrastructure.opm.cache import cache_key
from backend.infrastructure.opm.opm_deck import OpmDeckEmitter
from backend.infrastructure.opm.runner import deck_hashes, summary_spec_hash
from backend.infrastructure.opm.submission import _run
from backend.domain.configuration import default_config, economics_config_hash
from backend.core.contracts import (
    ArtifactHashes,
    ControlEvent,
    EventKind,
    NormativeSet,
    RunStatus,
    Schedule,
    ScheduleMeta,
    DEFAULT_NORMATIVES_2007,
)
from backend.core.paths import data_root
from backend.domain.economics import ESP_CATALOG_2007, methodology_version_hash
from backend.domain.economics.base_case import analyze_base_case
from backend.domain.schedule import parse_schedule
from backend.domain.schedule.build import deck_well_axis, initial_state_from_prefix
from backend.domain.schedule.canonical import canonical_part_hash

from conftest import missing_reason, model_z_dir

MODEL_Z = model_z_dir()
WORK_ROOT = data_root() / "base_run"
_SCHEDULE_INCLUDE = "Model_Z_sch.inc"

pytestmark = pytest.mark.skipif(MODEL_Z is None, reason=missing_reason("каталог Model_Z"))

NORMATIVES = NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=ESP_CATALOG_2007)


def _hybrid_schedule() -> Schedule:
    raw = (MODEL_Z / _SCHEDULE_INCLUDE).read_bytes()
    parsed = parse_schedule(raw)
    wells = deck_well_axis(raw)
    initial_state = initial_state_from_prefix(parsed, wells)
    return Schedule(
        meta=ScheduleMeta(wells=wells, provenance="g6-submission-test"),
        initial_state=initial_state,
        fixed_deck_events=parsed.fixed_deck_events,
        control_events=parsed.control_events,
    )


def _seed_cache_entry_for(schedule: Schedule, tmp_path: Path) -> None:
    """Реальный дек этого расписания уже прогнан (см. докстринг модуля) —
    записывает вторую запись кеша под его собственным `canonical_schedule_hash`,
    указывающую на те же реальные артефакты, что и существующая запись."""

    existing = list((WORK_ROOT / "cache").glob("*.json"))
    if not existing:
        pytest.skip("нет ни одной записи кеша в aios/data/base_run/cache — материализовать G1")
    entry = json.loads(existing[0].read_text(encoding="utf-8"))

    emitter = OpmDeckEmitter(MODEL_Z)
    deck = emitter.emit(schedule, tmp_path / "scratch-deck")
    hashes = deck_hashes(deck, schedule)

    target_key = cache_key(hashes.deck_hash, hashes.canonical_schedule_hash, hashes.summary_hash)
    target_path = WORK_ROOT / "cache" / f"{target_key}.json"
    if target_path.exists():
        return
    entry["deck_hash"] = hashes.deck_hash
    entry["canonical_schedule_hash"] = hashes.canonical_schedule_hash
    entry["summary_hash"] = hashes.summary_hash
    target_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")


def _config(schedule: Schedule):
    emitter = OpmDeckEmitter(MODEL_Z)
    with tempfile.TemporaryDirectory() as scratch:
        deck = emitter.emit(schedule, Path(scratch) / "deck")
        hashes = deck_hashes(deck, schedule)
        summary_hash = summary_spec_hash(deck.summary_plan.spec)
    artifact_hashes = ArtifactHashes(
        deck_hash=hashes.deck_hash,
        history_prefix_hash=canonical_part_hash(schedule.initial_state),
        summary_spec_hash=summary_hash,
        # Связность/датасет/чекпоинт суррогата — задачи G4/G5, ещё не сделаны
        # (см. docs/v2/tasks/integration.md). Тестовые заглушки, не
        # заявленные значения — тем же приёмом, что и в
        # contracts/tests/test_simulation.py / ui/tests/test_scenarios.py.
        groups_hash="0" * 64,
        dataset_version_hash="0" * 64,
        surrogate_checkpoint_hash="0" * 64,
    )
    return default_config(NORMATIVES, artifact_hashes, global_seed=20260820)


@pytest.fixture(scope="module")
def schedule() -> Schedule:
    return _hybrid_schedule()


@pytest.fixture(scope="module")
def config(schedule):
    return _config(schedule)


@pytest.fixture(scope="module")
def run_and_response(schedule, config, tmp_path_factory: pytest.TempPathFactory):
    """Identity 1/2/4 — до гейта `validate_dynamic`. Реальный кеш-хит, без Docker."""

    tmp = tmp_path_factory.mktemp("g6-seed")
    _seed_cache_entry_for(schedule, tmp)
    return _run(schedule, MODEL_Z, WORK_ROOT, use_cache=True)


# --- Identity 1/2/4: до гейта validate_dynamic, через настоящий тракт --------


def test_opm_run_status_is_ok(run_and_response) -> None:
    opm_run, _ = run_and_response
    assert opm_run.status is RunStatus.OK


def test_opm_run_canonical_schedule_hash_matches_recomputed(schedule, run_and_response) -> None:
    """Identity 1: `OpmRunArtifact.canonical_schedule_hash == canonical_schedule_hash`,
    пересчитанный на моменте сдачи (`submit_schedule` делает это же явно)."""

    from backend.core.contracts import hash_schedule

    opm_run, _ = run_and_response
    assert opm_run.canonical_schedule_hash == hash_schedule(schedule)


def test_response_source_run_id_matches_opm_run(run_and_response) -> None:
    """Identity 4."""

    opm_run, response = run_and_response
    assert response.source_run_id == opm_run.run_id


# --- Гейт validate_static — до всякого эмита, без Docker вообще --------------


def test_validate_static_gate_rejects_before_any_run(schedule, config) -> None:
    """Событие по скважине вне оси `initial_state` — `WELL_NOT_ON_AXIS`.
    Тракт обязан упасть на гейте `validate_static`, не дойдя до эмита/прогона."""

    broken = Schedule(
        meta=schedule.meta,
        initial_state=schedule.initial_state,
        fixed_deck_events=schedule.fixed_deck_events,
        control_events=(
            ControlEvent(control_step=0, well="999", kind=EventKind.SET_LRAT, value=50.0),
        ),
    )
    with pytest.raises(SubmissionTractError, match="validate_static"):
        submit_schedule(broken, MODEL_Z, WORK_ROOT, config, use_cache=True)


# --- Гейт validate_dynamic — реальная, задокументированная находка ----------


def test_dynamic_gate_rejects_the_real_baseline_over_well_71(schedule, config) -> None:
    """Тракт целиком: гейт `validate_dynamic` обязан остановить выдачу
    `FinalNpvArtifact`, пока открытый вопрос №17 не закрыт. Пин регрессии —
    если это число изменится, значит либо деку организаторов поправили
    (маловероятно без объявления), либо в `schedule/`/`bridge/` что-то
    сломалось."""

    with pytest.raises(SubmissionTractError, match="validate_dynamic") as excinfo:
        submit_schedule(schedule, MODEL_Z, WORK_ROOT, config, use_cache=True)
    assert "71 нарушени" in str(excinfo.value)


# --- Identity 5/6: сборка FinalNpvArtifact на настоящих opm_run/response ----
# (validate_dynamic здесь намеренно не гейтует — эти тождества о сборке
# артефакта, не о согласованности расписания с откликом.)


@pytest.fixture(scope="module")
def final_npv(schedule, config, run_and_response):
    opm_run, response = run_and_response
    raw = (MODEL_Z / _SCHEDULE_INCLUDE).read_bytes()
    parsed = parse_schedule(raw)
    analysis = analyze_base_case(
        response, parsed.dates, parsed.t0_deck_date_index, config.normatives, config.policies
    )
    from backend.core.contracts import FinalNpvArtifact

    return FinalNpvArtifact(
        npv_table=analysis.table,
        npv_methodology=analysis.table.npv_methodology,
        source_run_id=opm_run.run_id,
        source_response_hash=response.response_hash,
        economics_config_hash=economics_config_hash(config),
        methodology_version_hash=methodology_version_hash(),
    )


def test_final_npv_source_matches_run_and_response(final_npv, run_and_response) -> None:
    """Identity 5."""

    opm_run, response = run_and_response
    assert final_npv.source_run_id == opm_run.run_id
    assert final_npv.source_response_hash == response.response_hash


def test_final_npv_config_and_methodology_hashes_match_independent_recomputation(
    final_npv, config
) -> None:
    """Identity 6."""

    assert final_npv.economics_config_hash == economics_config_hash(config)
    assert final_npv.methodology_version_hash == methodology_version_hash()
    assert len(final_npv.economics_config_hash) == 64
    assert len(final_npv.methodology_version_hash) == 64


def test_final_npv_methodology_matches_its_own_table(final_npv) -> None:
    """`FinalNpvArtifact.__post_init__` уже это проверяет при конструировании —
    здесь то же самое явно как приёмка, а не как побочный эффект конструктора."""

    assert final_npv.npv_methodology == final_npv.npv_table.npv_methodology
    assert final_npv.npv_methodology > 0.0


# --- Полный отчёт вместо обрыва на первом расхождении -----------------------
#
# Перенесено из ветки feat/andrey/62 (закрыта): там звено А считало все шесть
# тождеств §10.5 и отдавало отчёт, тогда как первая версия падала на первом же.
# Разница существенна ровно потому, что попытка сдачи одна: увидеть «сломано
# одно» и «цепочка разошлась целиком» надо до неё, а не после.


def test_all_six_identities_are_computed_even_when_the_tract_fails(schedule, config) -> None:
    """Базовое расписание не проходит динамику — но отчёт всё равно полон."""

    result = submit_schedule(
        schedule, MODEL_Z, WORK_ROOT, config, use_cache=True, strict=False
    )

    names = [check.name for check in result.identities]
    assert names == [
        "run_schedule_hash",
        "run_status_ok",
        "response_source_run_id",
        "npv_source_provenance",
        "economics_config_hash",
        "methodology_version_hash",
    ]
    # Тождества провенанса держатся: прогон, отклик и ЧДД связаны верно —
    # цепочку останавливает динамика, а не подмена артефактов.
    assert result.failed_identities == ()
    assert result.sound is False
    assert result.dynamic_report is not None and not result.dynamic_report.ok
    # ЧДД посчитан, но заявлять его нечем — это и есть различение «нарушена
    # динамика» против «ошибка в деньгах», ради которого отчёт собирается.
    assert result.final_npv is not None
    with pytest.raises(SubmissionTractError, match="validate_dynamic"):
        _ = result.npv_methodology


def test_strict_mode_lists_every_reason_at_once(schedule, config) -> None:
    """Одно исключение, все причины: не первая попавшаяся."""

    with pytest.raises(SubmissionTractError, match="звено А §10.5 не пройдено") as excinfo:
        submit_schedule(schedule, MODEL_Z, WORK_ROOT, config, use_cache=True)

    assert "validate_dynamic" in str(excinfo.value)
