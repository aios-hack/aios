"""Constraints — условия кейса. README.md §5."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class WellOutage:
    well: str
    control_step_from: int
    control_step_to: int


@dataclass(frozen=True, slots=True)
class Constraints:
    """Сериализуемый документ: порождает интерфейс, читает политика.

    Пустой документ (все поля пустые словари/кортежи) означает отсутствие
    ограничений сверх физических, а не отсутствие данных.
    """

    injection_limits: dict[int, float] = field(default_factory=dict)  # год -> м³/сут
    liquid_limits: dict[int, float] = field(default_factory=dict)  # год -> м³/сут
    production_floors: dict[int, float] = field(default_factory=dict)  # год -> т/сут
    watercut_limits: dict[int, float] = field(default_factory=dict)  # год -> доля
    well_outages: tuple[WellOutage, ...] = field(default_factory=tuple)
    infrastructure: dict[str, object] = field(default_factory=dict)  # свободные пары
