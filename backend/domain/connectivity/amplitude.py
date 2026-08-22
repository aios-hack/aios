from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from backend.domain.connectivity.doe import Amplitude, Level
from backend.domain.connectivity.setpoints import StepDistribution

MIN_SWEEP_PROBES = 3
MAX_SWEEP_PROBES = 4


@dataclass(frozen=True, slots=True)
class ProbeSelection:
    wells: tuple[str, ...]
    neighbour_count: dict[str, int]

    def __post_init__(self) -> None:
        if len(self.wells) < MIN_SWEEP_PROBES:
            raise ValueError(
                f"свип требует минимум {MIN_SWEEP_PROBES} нагнетательных с разной "
                f"плотностью окружения, выбрано {len(self.wells)}"
            )
        if len(self.wells) > MAX_SWEEP_PROBES:
            raise ValueError(
                f"свип рассчитан максимум на {MAX_SWEEP_PROBES} скважин, "
                f"выбрано {len(self.wells)}"
            )
        if len(set(self.wells)) != len(self.wells):
            raise ValueError("скважина названа в свипе дважды")
        missing = set(self.wells) - set(self.neighbour_count)
        if missing:
            raise ValueError(f"нет плотности окружения для {sorted(missing)}")

    @property
    def density_spread(self) -> int:
        counts = [self.neighbour_count[well] for well in self.wells]
        return max(counts) - min(counts)


def headroom_injectors(
    injectors: Sequence[str],
    baseline_rate_by_well: Mapping[str, float],
    baseline_setpoint_by_well: Mapping[str, float],
    tolerance: float,
) -> tuple[str, ...]:
    if not (0.0 <= tolerance < 1.0):
        raise ValueError(f"допуск недобора {tolerance} вне [0, 1)")
    missing = set(injectors) - set(baseline_rate_by_well)
    missing |= set(injectors) - set(baseline_setpoint_by_well)
    if missing:
        raise ValueError(
            f"нет базовой приёмистости или уставки для {sorted(missing)}: "
            f"запас по давлению определяется замером, не предположением"
        )
    free: list[str] = []
    for well in injectors:
        setpoint = baseline_setpoint_by_well[well]
        if setpoint <= 0.0:
            continue
        shortfall = max(setpoint - baseline_rate_by_well[well], 0.0) / setpoint
        if shortfall <= tolerance:
            free.append(well)
    return tuple(sorted(free))


def select_probe_injectors(
    injectors: Sequence[str],
    neighbour_count: Mapping[str, int],
    probes: int,
) -> ProbeSelection:
    if not (MIN_SWEEP_PROBES <= probes <= MAX_SWEEP_PROBES):
        raise ValueError(
            f"число скважин свипа {probes} вне {MIN_SWEEP_PROBES}…{MAX_SWEEP_PROBES}"
        )
    if len(injectors) < probes:
        raise ValueError(
            f"нагнетательных с запасом по давлению {len(injectors)}, на свип "
            f"нужно {probes}: скважина, уже стоящая на пределе, повышения "
            f"уставки не реализует и амплитуду не измеряет"
        )
    missing = set(injectors) - set(neighbour_count)
    if missing:
        raise ValueError(f"нет плотности окружения для {sorted(missing)}")
    ordered = sorted(injectors, key=lambda well: (neighbour_count[well], well))
    if probes == 1:
        picked = [ordered[0]]
    else:
        picked = []
        for index in range(probes):
            position = round(index * (len(ordered) - 1) / (probes - 1))
            candidate = ordered[position]
            step = 1
            while candidate in picked:
                forward = position + step
                backward = position - step
                if forward < len(ordered) and ordered[forward] not in picked:
                    candidate = ordered[forward]
                elif backward >= 0 and ordered[backward] not in picked:
                    candidate = ordered[backward]
                step += 1
            picked.append(candidate)
    wells = tuple(sorted(picked))
    return ProbeSelection(
        wells=wells,
        neighbour_count={well: neighbour_count[well] for well in wells},
    )


def sweep_amplitudes(
    distribution: StepDistribution,
    relative_levels: Sequence[float],
) -> tuple[Amplitude, ...]:
    if not relative_levels:
        raise ValueError("свип без единого уровня амплитуды не строится")
    if sorted(relative_levels) != list(relative_levels):
        raise ValueError("уровни свипа обязаны строго возрастать")
    if len(set(relative_levels)) != len(relative_levels):
        raise ValueError("уровень свипа назван дважды")
    level = distribution.median_level_m3_per_day
    if level <= 0.0:
        raise ValueError("медианный уровень закачки не положителен")
    amplitudes: list[Amplitude] = []
    for relative in relative_levels:
        if relative <= 0.0:
            raise ValueError(f"относительная амплитуда {relative} не положительна")
        step = relative * level
        amplitudes.append(
            Amplitude(
                base_level_m3_per_day=level,
                step_low_m3_per_day=step,
                step_high_m3_per_day=step,
            )
        )
    return tuple(amplitudes)


def prior_bracket(distribution: StepDistribution, coverage: float) -> tuple[float, float]:
    return distribution.amplitude_prior(coverage)


FLOAT32_MANTISSA_BITS = 23


def numerical_noise_floor(baseline_cumulative_m3: float, safety_factor: float) -> float:
    if baseline_cumulative_m3 < 0.0:
        raise ValueError(
            f"накопленная добыча базового прогона {baseline_cumulative_m3} отрицательна"
        )
    if safety_factor < 1.0:
        raise ValueError(
            f"запас {safety_factor} меньше единицы: порог различимости не может "
            f"быть ниже разрешения самого носителя"
        )
    return baseline_cumulative_m3 * (2.0 ** -FLOAT32_MANTISSA_BITS) * safety_factor


@dataclass(frozen=True, slots=True)
class ProbeOutcome:
    well: str
    level: Level
    amplitude: Amplitude
    target_m3_per_day: float
    actual_m3_per_day: float
    baseline_cumulative_m3: float
    perturbed_cumulative_m3: float

    @property
    def realized_delta_m3_per_day(self) -> float:
        return self.actual_m3_per_day - self.baseline_rate_m3_per_day

    @property
    def baseline_rate_m3_per_day(self) -> float:
        step = self.amplitude.step_m3_per_day
        if self.level is Level.HIGH:
            return self.target_m3_per_day - step
        return self.target_m3_per_day + step

    @property
    def shortfall_m3_per_day(self) -> float:
        return max(self.target_m3_per_day - self.actual_m3_per_day, 0.0)

    @property
    def relative_shortfall(self) -> float:
        if self.target_m3_per_day <= 0.0:
            return 0.0
        return self.shortfall_m3_per_day / self.target_m3_per_day

    @property
    def response_m3(self) -> float:
        return self.perturbed_cumulative_m3 - self.baseline_cumulative_m3


@dataclass(frozen=True, slots=True)
class AmplitudeProbe:
    relative_amplitude: float
    amplitude: Amplitude
    outcomes: tuple[ProbeOutcome, ...]
    noise_floor_m3: float

    def __post_init__(self) -> None:
        if self.relative_amplitude <= 0.0:
            raise ValueError(
                f"относительная амплитуда {self.relative_amplitude} не положительна"
            )
        if not self.outcomes:
            raise ValueError("замер амплитуды без единого исхода прогона")
        if self.noise_floor_m3 < 0.0:
            raise ValueError(f"уровень шума {self.noise_floor_m3} отрицателен")

    @property
    def realized_drive_m3_per_day(self) -> float:
        return sum(abs(o.realized_delta_m3_per_day) for o in self.outcomes)

    @property
    def response_m3(self) -> float:
        return sum(abs(o.response_m3) for o in self.outcomes)

    @property
    def gain(self) -> float:
        drive = self.realized_drive_m3_per_day
        if drive <= 0.0:
            raise ValueError(
                f"амплитуда {self.relative_amplitude}: фактическое воздействие нулевое, "
                f"отношение отклика к воздействию не определено"
            )
        return self.response_m3 / drive

    def distinguishable(self) -> bool:
        return self.response_m3 > self.noise_floor_m3

    def shortfalls(self, tolerance: float) -> tuple[ProbeOutcome, ...]:
        return tuple(o for o in self.outcomes if o.relative_shortfall > tolerance)

    def achievability_ok(self, tolerance: float) -> dict[str, bool]:
        failing = {o.well for o in self.shortfalls(tolerance)}
        return {o.well: o.well not in failing for o in self.outcomes}

    def systematic_shortfall(self, tolerance: float) -> bool:
        raised = [o for o in self.outcomes if o.level is Level.HIGH]
        if not raised:
            return False
        failing = [o for o in raised if o.relative_shortfall > tolerance]
        return len(failing) * 2 > len(raised)


@dataclass(frozen=True, slots=True)
class AmplitudeMeasurement:
    probes: tuple[AmplitudeProbe, ...]
    achievability_tolerance: float
    linearity_tolerance: float

    def __post_init__(self) -> None:
        if not self.probes:
            raise ValueError("замер без единой точки свипа")
        levels = [probe.relative_amplitude for probe in self.probes]
        if sorted(levels) != levels:
            raise ValueError("точки свипа обязаны идти по возрастанию амплитуды")
        if len(set(levels)) != len(levels):
            raise ValueError("точка свипа повторена")
        if not (0.0 <= self.achievability_tolerance < 1.0):
            raise ValueError(
                f"допуск недобора {self.achievability_tolerance} вне [0, 1)"
            )
        if self.linearity_tolerance <= 0.0:
            raise ValueError(
                f"допуск нелинейности {self.linearity_tolerance} не положителен"
            )

    def gains(self) -> tuple[float, ...]:
        return tuple(probe.gain for probe in self.probes)

    def reference_gain(self) -> float:
        return self.probes[0].gain

    def gain_drift(self) -> tuple[float, ...]:
        reference = self.reference_gain()
        if reference == 0.0:
            raise ValueError(
                "отклик на наименьшей амплитуде нулевой: точка отсчёта линейности "
                "не определена, свип начат ниже уровня шума"
            )
        return tuple(abs(gain - reference) / abs(reference) for gain in self.gains())

    def linear_probes(self) -> tuple[AmplitudeProbe, ...]:
        accepted: list[AmplitudeProbe] = []
        for probe, drift in zip(self.probes, self.gain_drift()):
            if drift > self.linearity_tolerance:
                break
            accepted.append(probe)
        return tuple(accepted)

    def breakpoint_relative_amplitude(self) -> float | None:
        linear = self.linear_probes()
        if len(linear) == len(self.probes):
            return None
        return self.probes[len(linear)].relative_amplitude

    def admissible_probes(self) -> tuple[AmplitudeProbe, ...]:
        return tuple(
            probe
            for probe in self.linear_probes()
            if probe.distinguishable()
            and not probe.systematic_shortfall(self.achievability_tolerance)
        )


@dataclass(frozen=True, slots=True)
class AmplitudeVerdict:
    chosen: Amplitude
    relative_amplitude: float
    breakpoint_relative_amplitude: float | None
    limited_by: str
    probes_run: int
    gains: tuple[float, ...]
    achievability_ok: dict[str, bool]

    @property
    def measured(self) -> bool:
        return self.probes_run > 0


LIMITED_BY_LINEARITY = "нелинейность"
LIMITED_BY_ACHIEVABILITY = "недостижимость"
LIMITED_BY_NOISE = "шум"
LIMITED_BY_SWEEP_RANGE = "верх свипа"


def _limiting_reason(
    measurement: AmplitudeMeasurement, chosen: AmplitudeProbe
) -> str:
    index = measurement.probes.index(chosen)
    if index == len(measurement.probes) - 1:
        return LIMITED_BY_SWEEP_RANGE
    following = measurement.probes[index + 1]
    if following.systematic_shortfall(measurement.achievability_tolerance):
        return LIMITED_BY_ACHIEVABILITY
    if not following.distinguishable():
        return LIMITED_BY_NOISE
    return LIMITED_BY_LINEARITY


def choose_amplitude(measurement: AmplitudeMeasurement) -> AmplitudeVerdict:
    admissible = measurement.admissible_probes()
    if not admissible:
        raise ValueError(
            "ни одна точка свипа не прошла: отклик не отличим от шума либо "
            "верхний уровень систематически не добирается. Амплитуда не "
            "замерена — назначать её «на глаз» протокол §8.3 запрещает"
        )
    chosen = admissible[-1]
    return AmplitudeVerdict(
        chosen=chosen.amplitude,
        relative_amplitude=chosen.relative_amplitude,
        breakpoint_relative_amplitude=measurement.breakpoint_relative_amplitude(),
        limited_by=_limiting_reason(measurement, chosen),
        probes_run=len(measurement.probes),
        gains=measurement.gains(),
        achievability_ok=chosen.achievability_ok(measurement.achievability_tolerance),
    )


def demote_plan_amplitude(
    amplitude: Amplitude, verdict: AmplitudeVerdict
) -> Amplitude:
    if verdict.relative_amplitude <= 0.0:
        raise ValueError("замеренная относительная амплитуда не положительна")
    measured = verdict.chosen.step_m3_per_day
    if amplitude.step_m3_per_day <= measured:
        return amplitude
    return Amplitude(
        base_level_m3_per_day=amplitude.base_level_m3_per_day,
        step_low_m3_per_day=measured,
        step_high_m3_per_day=measured,
    )
