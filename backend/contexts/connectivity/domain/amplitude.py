from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from backend.contexts.connectivity.domain.doe import Amplitude, Level
from backend.contexts.connectivity.domain.setpoints import StepDistribution

MIN_SWEEP_PROBES = 3
MAX_SWEEP_PROBES = 4


@dataclass(frozen=True, slots=True)
class ProbeSelection:
    wells: tuple[str, ...]
    neighbour_count: dict[str, int]

    def __post_init__(self) -> None:
        if len(self.wells) < MIN_SWEEP_PROBES:
            raise ValueError(
                f"the sweep needs at least {MIN_SWEEP_PROBES} injectors with different "
                f"neighbourhood density, {len(self.wells)} selected"
            )
        if len(self.wells) > MAX_SWEEP_PROBES:
            raise ValueError(
                f"the sweep is designed for at most {MAX_SWEEP_PROBES} wells, "
                f"{len(self.wells)} selected"
            )
        if len(set(self.wells)) != len(self.wells):
            raise ValueError("a well is named twice in the sweep")
        missing = set(self.wells) - set(self.neighbour_count)
        if missing:
            raise ValueError(f"no neighbourhood density for {sorted(missing)}")

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
        raise ValueError(f"shortfall tolerance {tolerance} outside [0, 1)")
    missing = set(injectors) - set(baseline_rate_by_well)
    missing |= set(injectors) - set(baseline_setpoint_by_well)
    if missing:
        raise ValueError(
            f"no baseline injectivity or setpoint for {sorted(missing)}: "
            f"pressure headroom is determined by measurement, not by assumption"
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
            f"sweep well count {probes} outside {MIN_SWEEP_PROBES}…{MAX_SWEEP_PROBES}"
        )
    if len(injectors) < probes:
        raise ValueError(
            f"{len(injectors)} injectors have pressure headroom, the sweep needs "
            f"{probes}: a well already at its limit cannot realise a setpoint "
            f"increase and measures no amplitude"
        )
    missing = set(injectors) - set(neighbour_count)
    if missing:
        raise ValueError(f"no neighbourhood density for {sorted(missing)}")
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
        raise ValueError("a sweep cannot be built without a single amplitude level")
    if sorted(relative_levels) != list(relative_levels):
        raise ValueError("sweep levels must strictly increase")
    if len(set(relative_levels)) != len(relative_levels):
        raise ValueError("a sweep level is named twice")
    level = distribution.median_level_m3_per_day
    if level <= 0.0:
        raise ValueError("the median injection level is not positive")
    amplitudes: list[Amplitude] = []
    for relative in relative_levels:
        if relative <= 0.0:
            raise ValueError(f"relative amplitude {relative} is not positive")
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
            f"cumulative production of the baseline run {baseline_cumulative_m3} is negative"
        )
    if safety_factor < 1.0:
        raise ValueError(
            f"safety factor {safety_factor} is below one: the distinguishability "
            f"threshold cannot be below the resolution of the carrier itself"
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
                f"relative amplitude {self.relative_amplitude} is not positive"
            )
        if not self.outcomes:
            raise ValueError("an amplitude measurement without a single run outcome")
        if self.noise_floor_m3 < 0.0:
            raise ValueError(f"noise floor {self.noise_floor_m3} is negative")

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
                f"amplitude {self.relative_amplitude}: the actual drive is zero, "
                f"the response-to-drive ratio is undefined"
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
            raise ValueError("a measurement without a single sweep probe")
        levels = [probe.relative_amplitude for probe in self.probes]
        if sorted(levels) != levels:
            raise ValueError("sweep probes must be ordered by increasing amplitude")
        if len(set(levels)) != len(levels):
            raise ValueError("a sweep probe is repeated")
        if not (0.0 <= self.achievability_tolerance < 1.0):
            raise ValueError(
                f"shortfall tolerance {self.achievability_tolerance} outside [0, 1)"
            )
        if self.linearity_tolerance <= 0.0:
            raise ValueError(
                f"nonlinearity tolerance {self.linearity_tolerance} is not positive"
            )

    def gains(self) -> tuple[float, ...]:
        return tuple(probe.gain for probe in self.probes)

    def reference_gain(self) -> float:
        return self.probes[0].gain

    def gain_drift(self) -> tuple[float, ...]:
        reference = self.reference_gain()
        if reference == 0.0:
            raise ValueError(
                "the response at the smallest amplitude is zero: the linearity "
                "reference point is undefined, the sweep starts below the noise floor"
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


LIMITED_BY_LINEARITY = "nonlinearity"
LIMITED_BY_ACHIEVABILITY = "unachievable"
LIMITED_BY_NOISE = "noise"
LIMITED_BY_SWEEP_RANGE = "top of sweep"


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
            "not a single sweep probe passed: the response is indistinguishable "
            "from noise or the top level is systematically not reached. The "
            "amplitude is not measured — protocol section 8.3 forbids "
            "assigning it by eye"
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
        raise ValueError("the measured relative amplitude is not positive")
    measured = verdict.chosen.step_m3_per_day
    if amplitude.step_m3_per_day <= measured:
        return amplitude
    return Amplitude(
        base_level_m3_per_day=amplitude.base_level_m3_per_day,
        step_low_m3_per_day=measured,
        step_high_m3_per_day=measured,
    )
