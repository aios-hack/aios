"""SummarySpec, RunResult и provenance финальной сдачи. README.md §6, §6a."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .economics import NpvTable
from .response import IntervalResponse, StateAtDate

# Девять логических выходов заданы форматом входа эталонного расчётчика ЧДД:
# REQUIRED_COLUMNS в ../models/CHDD_PYTHON/chdd_model.py. Это не буквальный
# список ключей OPM: Flow 2026.04 не поддерживает массовые WOMT/WOMR.
SUMMARY_EXPORT_KEYS = (
    "WLPT", "WOMT", "WWIT",  # накопленные
    "WLPR", "WOMR", "WWIR",  # мгновенные дебиты и приёмистость
    "WTHP", "WBHP",  # устьевое и забойное давление
    "WEFF",  # в экономику не входит, но колонка входного файла обязательна
)

# Прямые well-level векторы, которые реально запрашиваются у OPM. WMCTL
# подтверждён настоящим прогоном Flow 2026.04 и поэтому больше не опционален.
OPM_WELL_SUMMARY_KEYS = (
    "WLPT", "WWIT",
    "WLPR", "WWIR",
    "WTHP", "WBHP", "WEFF",
    "WMCTL",
)

# Масса нефти собирается из объёмов подключений с плотностью PVT-региона
# каждой ячейки. Одна плотность на скважину неверна: 23 скважины Model_Z
# вскрывают оба PVTNUM.
OPM_CONNECTION_SUMMARY_KEYS = ("COPT", "COPR")

# Временный псевдоним для веток, начатых до разведения экспортных и OPM-ключей.
# Новый код должен использовать SUMMARY_EXPORT_KEYS.
REQUIRED_SUMMARY_KEYS = SUMMARY_EXPORT_KEYS


@dataclass(frozen=True, slots=True)
class SummarySpec:
    """Логический экспорт и фактические векторы секции SUMMARY.

    ``export_keys`` — девять полей, которые обязан получить эталонный
    расчётчик. ``opm_well_keys`` и ``opm_connection_keys`` — буквальные
    ключи, которые пишет OpmDeckEmitter. WOMT/WOMR восстанавливает
    ResponseLoader из COPT/COPR по PVTNUM и DENSITY каждой ячейки.
    """

    export_keys: tuple[str, ...] = SUMMARY_EXPORT_KEYS
    opm_well_keys: tuple[str, ...] = OPM_WELL_SUMMARY_KEYS
    opm_connection_keys: tuple[str, ...] = OPM_CONNECTION_SUMMARY_KEYS

    def __post_init__(self) -> None:
        expected = (
            ("export_keys", self.export_keys, SUMMARY_EXPORT_KEYS),
            ("opm_well_keys", self.opm_well_keys, OPM_WELL_SUMMARY_KEYS),
            (
                "opm_connection_keys",
                self.opm_connection_keys,
                OPM_CONNECTION_SUMMARY_KEYS,
            ),
        )
        for field, actual, required in expected:
            if actual != required:
                raise ValueError(
                    f"SummarySpec.{field}: ожидалось {required!r}, получено {actual!r}"
                )


class RunStatus(Enum):
    OK = "OK"
    NOT_CONVERGED = "NOT_CONVERGED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class RunResult:
    """Падение прогона — данные, а не исключение (§4.4 базы знаний)."""

    run_id: str
    status: RunStatus
    deck_hash: str  # только статическая часть дека, ключ кеша §4.5
    canonical_schedule_hash: str  # единственное имя, см. hashing.py
    summary_hash: str
    artifacts: tuple[str, ...]  # пути, вне git
    wallclock_seconds: float
    message: str


@dataclass(frozen=True, slots=True)
class OpmRunArtifact(RunResult):
    """RunResult финального OPM-прогона + единственное новое поле.

    Не заводит нового поля для хеша расписания — canonical_schedule_hash
    уже есть в RunResult. content_hash_opm — хеш байтов сгенерированного
    OPM-дека целиком (статика + расписание), не то же самое, что deck_hash
    (только статика) и не то же самое, что canonical_schedule_hash
    (семантический хеш Schedule, не файла).
    """

    content_hash_opm: str


@dataclass(frozen=True, slots=True)
class ResponseArtifact:
    """Результат ResponseLoader, а не безымянная пара массивов."""

    source_run_id: str  # обязан равняться OpmRunArtifact.run_id
    response_hash: str  # хеш канонической сериализации обоих типов
    state_at_date: tuple[StateAtDate, ...]
    interval_response: tuple[IntervalResponse, ...]


@dataclass(frozen=True, slots=True)
class FinalNpvArtifact:
    """Единственный разрешённый источник заявленного числа. README.md §6a."""

    npv_table: NpvTable
    npv_methodology: float  # рубли, то самое число, которое заявляется
    source_run_id: str  # тот же OpmRunArtifact.run_id
    source_response_hash: str  # тот же ResponseArtifact.response_hash
    economics_config_hash: str  # хеш policies+normatives, не Config целиком
    methodology_version_hash: str  # хеш версии кода Economics

    def __post_init__(self) -> None:
        if self.npv_methodology != self.npv_table.npv_methodology:
            raise ValueError(
                "FinalNpvArtifact.npv_methodology разошлось с "
                "npv_table.npv_methodology — заявляется число не из этого "
                "разложения"
            )


@dataclass(frozen=True, slots=True)
class SubmissionArtifact:
    """Не реализован до подтверждения формата организаторами (§3.1).

    Форма зафиксирована на будущее. canonical_schedule_hash обязан
    равняться тому же значению, что и OpmRunArtifact.canonical_schedule_hash.
    """

    canonical_schedule_hash: str
    content_hash_submission: str
