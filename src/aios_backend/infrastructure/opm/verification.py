"""Внешний цикл верификации — задача 39, §10.1 и §10.2.

Схема раунда из §10.1 дословно:

    раунд r:  оптимизатор ищет θ на суррогате внутри области доверия
              top-k по предсказанному ЧДД → прогон на OPM → истинный ЧДД
              сошлось  → область расширяется
              разошлось → область сужается, k прогонов уходят в обучающую
                          выборку, суррогат дообучается
    конец цикла: лучший кандидат по всем раундам переоценивается последней
              версией суррогата и последней областью доверия, возвращается
              self_consistent

## Область доверия — это ограничение, а не отбор постфактум

§10.2: «Кандидат допустим, пока `ood_score ≤ τ`». Здесь это выражено через
ту же границу §6.1, что и всё остальное: выход за область — не поправка к
предсказанному ЧДД, а `feasible=False` с записью в `violations_by_scenario`.
Оптимизатор задачи 38 ранжирует так, что недопустимая точка не обгоняет
допустимую ни при каком ЧДД, поэтому кандидаты вне области не всплывают в
top-k вообще — а не отбрасываются после того, как их уже посчитали.

Отбор постфактум был бы хуже не только по стоимости: поиск, не знающий про
границу, уводит среднее облака за неё, и следующее поколение целиком
оказывается вне области.

## Переоценка последней версией обязательна

Кандидат найден суррогатом версии `r`, а к концу цикла обучение ушло на
`r+1`. Без переоценки цикл выбирает кандидата по модели, которой уже нет
(§10.1). Поэтому `self_consistent` считается **последней** версией и
**последним** τ, и приёмка проверяет именно версию, а не факт вызова.

## Это не источник сдаваемого числа

§10.1 и §10.5, и карточка Андрея повторяет это отдельно: «Задача 39
"финальная переоценка" — это внутренний выбор кандидата, не сдача. Легко
перепутать, потому что обе используют слово "финал"».

Поэтому `VerificationReport` не содержит поля с заявляемым ЧДД и не умеет
собрать `FinalNpvArtifact`: он отдаёт лучшего кандидата — то есть θ, — а
число берётся отдельным финальным прогоном задачи 62. Приёмка проверяет
отсутствие такого поля структурно.

## Побочный результат — сдаваемые метрики

§10.3: «Таблица "предсказанный ЧДД против фактического" по всем проверенным
кандидатам и есть метрики качества суррогата, требуемые к сдаче. Отдельно
считать не нужно». `VerificationReport.table` хранит её целиком и в порядке
проверки, включая раунды, которые разошлись, — выбрасывать неудачные раунды
значило бы отчитываться по подобранной подвыборке.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from aios_backend.core.contracts import OptimizerResult, ScenarioViolation, Theta

from aios_backend.application.optimization.search import optimize


class VerificationError(ValueError):
    """Цикл нельзя поставить или продолжить: пустой бюджет, отсутствующая цель."""


# --- Что цикл получает извне ------------------------------------------------


@dataclass(frozen=True, slots=True)
class SurrogateVerdict:
    """Предсказание суррогата вместе с `ood_score`.

    Оба поля обязательны — та же дисциплина, что у `ScoredPrediction`
    (§5.2): детектор возвращается вместе с прогнозом всегда, не опцией.
    """

    predicted_npv: float
    ood_score: float

    def __post_init__(self) -> None:
        if self.ood_score < 0.0:
            raise VerificationError(f"ood_score={self.ood_score} отрицателен")


class SurrogateVersion(Protocol):
    """Одна версия суррогата. `version` растёт при каждом дообучении и
    служит доказательством, что переоценка сделана последней моделью."""

    version: int

    def __call__(self, theta: Theta) -> SurrogateVerdict: ...


@dataclass(frozen=True, slots=True)
class TruthVerdict:
    """Истина: настоящий прогон OPM плюс `Economics`.

    `run_id` и `canonical_schedule_hash` не украшение — без них строка
    таблицы §10.3 не связывается с прогоном, которым получена.
    """

    npv: float
    run_id: str
    canonical_schedule_hash: str

    def __post_init__(self) -> None:
        if not self.run_id:
            raise VerificationError("истинный ЧДД без run_id: строка ни с чем не связана")


class TruthOracle(Protocol):
    """θ → фактический ЧДД настоящим прогоном.

    Заглушкой быть не может (правило 3): цикл, у которого истина
    подделана, измеряет согласие суррогата с самим собой.
    """

    def __call__(self, theta: Theta) -> TruthVerdict: ...


class Retrainer(Protocol):
    """Дообучение: наблюдения разошедшегося раунда → новая версия суррогата."""

    def __call__(self, observations: tuple["CandidateCheck", ...]) -> SurrogateVersion: ...


class ConvergenceCriterion(Protocol):
    """«Прогноз сошёлся» — задача 40. Здесь только точка подключения:
    §10.4 оставляет сам критерий незамеренным, и цикл не вправе его
    выбирать за задачу 40."""

    def __call__(self, checks: Sequence["CandidateCheck"]) -> bool: ...


# --- Что цикл производит ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidateCheck:
    """Одна строка таблицы §10.3: что предсказали и что оказалось."""

    round_index: int
    theta: Theta
    predicted_npv: float
    actual_npv: float
    ood_score: float
    tau: float
    surrogate_version: int
    run_id: str
    canonical_schedule_hash: str

    @property
    def deviation(self) -> float:
        return self.predicted_npv - self.actual_npv

    @property
    def relative_deviation(self) -> float:
        if self.actual_npv == 0.0:
            raise VerificationError(
                f"{self.run_id}: фактический ЧДД равен нулю, "
                f"относительное отклонение не определено"
            )
        return self.deviation / abs(self.actual_npv)


@dataclass(frozen=True, slots=True)
class RoundReport:
    """Итог одного раунда: что проверили, сошлось ли, куда поехал τ."""

    index: int
    tau: float
    next_tau: float
    checks: tuple[CandidateCheck, ...]
    converged: bool
    retrained: bool
    surrogate_version: int
    optimizer_evaluations: int
    feasible_candidates: int

    def __post_init__(self) -> None:
        if not self.checks:
            raise VerificationError(
                f"раунд {self.index}: ни одного проверенного кандидата"
            )


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Итог цикла.

    Здесь **нет** поля с заявляемым ЧДД, и это не упущение: источник
    сдаваемого числа — финальный прогон задачи 62 (§10.5), а не цикл.
    Цикл отдаёт выбранную θ и таблицу «предсказано против факта».
    """

    rounds: tuple[RoundReport, ...]
    best: CandidateCheck
    self_consistent: bool
    final_tau: float
    final_surrogate_version: int
    reevaluation: SurrogateVerdict
    stop_reason: str

    def __post_init__(self) -> None:
        if not self.rounds:
            raise VerificationError("цикл без единого раунда")

    @property
    def table(self) -> tuple[CandidateCheck, ...]:
        """Сдаваемые метрики §10.3 — целиком, в порядке проверки, включая
        разошедшиеся раунды."""

        return tuple(check for report in self.rounds for check in report.checks)

    @property
    def total_runs(self) -> int:
        return len(self.table)

    @property
    def converged_rounds(self) -> int:
        return sum(1 for report in self.rounds if report.converged)


# --- Область доверия как ограничение ---------------------------------------


def trust_region_objective(surrogate: SurrogateVersion, tau: float):
    """Целевая функция §6.1, у которой область доверия — ограничение.

    Выход за область не поправляет `objective`, а снимает `feasible`:
    оптимизатор задачи 38 ранжирует недопустимые строго хуже допустимых,
    поэтому кандидаты вне области не попадают в top-k вовсе.
    """

    if tau < 0.0:
        raise VerificationError(f"порог области доверия τ={tau} отрицателен")

    def objective(theta: Theta) -> OptimizerResult:
        verdict = surrogate(theta)
        inside = verdict.ood_score <= tau
        violations = (
            ()
            if inside
            else (
                ScenarioViolation(
                    scenario_id="trust_region",
                    regret=verdict.ood_score - tau,
                    what=f"ood_score {verdict.ood_score:.4f} > τ {tau:.4f}",
                ),
            )
        )
        return OptimizerResult(
            objective=verdict.predicted_npv,
            feasible=inside,
            violations_by_scenario=violations,
            provenance={
                "surrogate_version": str(surrogate.version),
                "tau": repr(tau),
            },
        )

    return objective


# --- Цикл -------------------------------------------------------------------


def run_verification_loop(
    surrogate: SurrogateVersion,
    truth: TruthOracle,
    retrain: Retrainer,
    criterion: ConvergenceCriterion,
    start_theta: Theta,
    *,
    seed: int,
    initial_tau: float,
    runs_per_round: int,
    max_rounds: int,
    optimizer_evaluations_per_round: int,
    tau_expansion: float = 2.0,
    tau_contraction: float = 0.5,
) -> VerificationReport:
    """Внешний цикл верификации по §10.1.

    `runs_per_round` — это `Budgets.runs_per_verification_round` из конфига,
    и он считается прогонами OPM: на реальном Model_Z каждый стоит 513 с
    (`SURROGATE_HANDOFF.md` §2), поэтому k задаётся, а не подбирается.

    `tau_expansion > 1 > tau_contraction > 0`: сошлось — область растёт,
    разошлось — сжимается. Ни то ни другое не трогает суррогат напрямую;
    дообучение происходит только на разошедшемся раунде, и только на его
    наблюдениях (§10.1).
    """

    if runs_per_round < 1:
        raise VerificationError(f"прогонов на раунд {runs_per_round} < 1")
    if max_rounds < 1:
        raise VerificationError(f"раундов {max_rounds} < 1")
    if optimizer_evaluations_per_round < 1:
        raise VerificationError(
            f"бюджет оптимизатора {optimizer_evaluations_per_round} < 1"
        )
    if initial_tau < 0.0:
        raise VerificationError(f"начальный τ={initial_tau} отрицателен")
    if not tau_expansion > 1.0:
        raise VerificationError(f"расширение области {tau_expansion} не больше 1")
    if not 0.0 < tau_contraction < 1.0:
        raise VerificationError(f"сужение области {tau_contraction} вне (0, 1)")

    tau = float(initial_tau)
    current = surrogate
    rounds: list[RoundReport] = []
    stop_reason = f"пройдены все {max_rounds} раундов"

    for index in range(max_rounds):
        objective = trust_region_objective(current, tau)
        search = optimize(
            objective,
            start_theta,
            seed=seed + index,
            max_evaluations=optimizer_evaluations_per_round,
        )

        feasible = [item for item in search.history if item.result.feasible]
        if not feasible:
            # Область сжалась до пустоты: продолжать нечем, и притворяться,
            # что раунд состоялся, нельзя.
            stop_reason = (
                f"раунд {index}: внутри области доверия τ={tau:.6f} не нашлось "
                f"ни одного кандидата из {search.evaluations} оценённых"
            )
            break

        top = sorted(feasible, key=lambda item: -item.result.objective)[:runs_per_round]

        checks: list[CandidateCheck] = []
        for item in top:
            verdict = current(item.theta)
            observed = truth(item.theta)
            checks.append(
                CandidateCheck(
                    round_index=index,
                    theta=item.theta,
                    predicted_npv=item.result.objective,
                    actual_npv=observed.npv,
                    ood_score=verdict.ood_score,
                    tau=tau,
                    surrogate_version=current.version,
                    run_id=observed.run_id,
                    canonical_schedule_hash=observed.canonical_schedule_hash,
                )
            )

        converged = criterion(checks)
        next_tau = tau * (tau_expansion if converged else tau_contraction)
        retrained = False
        if not converged:
            # k прогонов уходят в обучающую выборку, суррогат дообучается.
            current = retrain(tuple(checks))
            retrained = True

        rounds.append(
            RoundReport(
                index=index,
                tau=tau,
                next_tau=next_tau,
                checks=tuple(checks),
                converged=converged,
                retrained=retrained,
                surrogate_version=checks[0].surrogate_version,
                optimizer_evaluations=search.evaluations,
                feasible_candidates=len(feasible),
            )
        )
        tau = next_tau

    if not rounds:
        raise VerificationError(
            f"цикл не сделал ни одного раунда: {stop_reason}"
        )

    # Лучший — по факту, а не по прогнозу: все кандидаты таблицы прогнаны
    # на OPM, и истина по ним известна.
    table = tuple(check for report in rounds for check in report.checks)
    best = max(table, key=lambda check: check.actual_npv)

    # Переоценка последней версией и последним τ (§10.1): кандидат найден
    # моделью версии r, а обучение ушло дальше.
    reevaluation = current(best.theta)
    inside_final_region = reevaluation.ood_score <= tau
    still_agrees = criterion(
        [
            CandidateCheck(
                round_index=best.round_index,
                theta=best.theta,
                predicted_npv=reevaluation.predicted_npv,
                actual_npv=best.actual_npv,
                ood_score=reevaluation.ood_score,
                tau=tau,
                surrogate_version=current.version,
                run_id=best.run_id,
                canonical_schedule_hash=best.canonical_schedule_hash,
            )
        ]
    )

    return VerificationReport(
        rounds=tuple(rounds),
        best=best,
        self_consistent=bool(inside_final_region and still_agrees),
        final_tau=tau,
        final_surrogate_version=current.version,
        reevaluation=reevaluation,
        stop_reason=stop_reason,
    )
