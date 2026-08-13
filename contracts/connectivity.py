"""Lambda и Groups — измеренная связность. README.md §7."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Lambda:
    """Оконная матрица влияния. Размер задаётся активным фондом окна, не
    фиксированным 92×41 — на 01.01.2007 нагнетательных 27, не 41.

    Σ по строке/столбцу matrix НЕ является инвариантом: это размерные
    коэффициенты чувствительности (прирост накопленной жидкости соседа на
    единицу закачки), а не безразмерные доли аллокации CRM.
    """

    window_start: date
    window_end: date
    producers: tuple[str, ...]
    injectors: tuple[str, ...]
    matrix: tuple[tuple[float, ...], ...]  # producers × injectors
    lag_months: int
    amplitude: float
    stability: float
    rank: int
    condition_number: float
    achievability_ok: dict[str, bool]  # по нагнетательной; диагностика,
    # не критерий исключения из регрессии

    def __post_init__(self) -> None:
        if len(self.matrix) != len(self.producers):
            raise ValueError("matrix.rows != len(producers)")
        if self.matrix and len(self.matrix[0]) != len(self.injectors):
            raise ValueError("matrix.cols != len(injectors)")


@dataclass(frozen=True, slots=True)
class Groups:
    """Нарезка фонда на участки. Алгоритм построения — не часть контракта
    (README.md §7); эта форма фиксирует только проверяемое без данных:
    покрытие 103/103, каждая группа содержит хотя бы одну нагнетательную,
    детерминированность при том же Lambda и seed.
    """

    groups: dict[str, tuple[str, ...]]  # id группы -> скважины
    lambda_hash: str  # хеш породившей матрицы
    group_hash: str
