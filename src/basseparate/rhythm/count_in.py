"""Count-in sequence construction from the active meter/tempo (M3.15)."""

from __future__ import annotations

import math
from fractions import Fraction

from basseparate.domain.count_in import CountInClick, CountInPlan
from basseparate.domain.meter import MeterMap
from basseparate.domain.metronome import ClickStrength
from basseparate.domain.rhythm import (
    CountInMode,
    CountInSettings,
    MusicalPosition,
)
from basseparate.domain.tempo import TempoMap


class CountInError(ValueError):
    """The count-in target cannot be resolved."""


def _musical(value: Fraction) -> MusicalPosition:
    return MusicalPosition(numerator=value.numerator, denominator=value.denominator)


def build_count_in_plan(
    tempo_map: TempoMap,
    meter_map: MeterMap,
    settings: CountInSettings,
    *,
    target_source_frame: int,
    playback_rate: float = 1.0,
    source_sample_rate: int,
) -> CountInPlan:
    """Build output-only count clicks ending immediately before the target.

    The local tempo at the target is held constant. Unavailable meter/tempo
    yields an explicit unavailable plan with a reason; 4/4 is never guessed.
    """
    if playback_rate <= 0 or source_sample_rate <= 0:
        raise CountInError("playback rate and sample rate must be positive")
    try:
        target = tempo_map.map_source_to_musical(target_source_frame)
        bpm = tempo_map.local_bpm_at_source(target_source_frame)
    except ValueError as exc:
        raise CountInError(str(exc)) from exc
    if settings.mode is CountInMode.OFF:
        return CountInPlan(
            mode=settings.mode,
            repetition=settings.repetition,
            available=False,
            reason="count-in is off",
            target_source_frame=target_source_frame,
            target_musical=target,
            local_quarter_bpm=bpm,
            playback_rate=playback_rate,
        )
    region = meter_map.region_at(target)
    if region is None:
        return CountInPlan(
            mode=settings.mode,
            repetition=settings.repetition,
            available=False,
            reason="no meter region at the playback start",
            target_source_frame=target_source_frame,
            target_musical=target,
            local_quarter_bpm=bpm,
            playback_rate=playback_rate,
        )
    grouping = list(region.candidate.grouping)
    denominator = region.candidate.denominator
    pulses_per_bar = len(grouping)
    bar_length = Fraction(4 * region.candidate.numerator, denominator)
    offset = target.as_quarter_notes() - region.start.as_quarter_notes()
    if offset < 0:
        raise CountInError("target lies before its meter region")
    bars_into = math.floor(offset / bar_length)
    bar_start = region.start.as_quarter_notes() + bars_into * bar_length
    phase = 0
    boundary = bar_start
    for index, part in enumerate(grouping):
        if target.as_quarter_notes() >= boundary:
            phase = index
        boundary += Fraction(part * 4, denominator)
    beat_boundary = bar_start
    for part in grouping[:phase]:
        beat_boundary += Fraction(part * 4, denominator)
    off_grid = target.as_quarter_notes() != beat_boundary
    bars = 1 if settings.mode is CountInMode.ONE_BAR else 2
    count_pulses = bars * pulses_per_bar
    total_quarters = sum(
        Fraction(grouping[(phase - count_pulses + index) % pulses_per_bar] * 4, denominator)
        for index in range(count_pulses)
    )
    total_frames = round(float(total_quarters) * 60.0 / bpm * source_sample_rate / playback_rate)
    durations: list[int] = []
    clicks: list[CountInClick] = []
    elapsed = 0.0
    for index in range(count_pulses):
        pulse_index = (phase - count_pulses + index) % pulses_per_bar
        quarters = Fraction(grouping[pulse_index] * 4, denominator)
        duration = float(quarters) * 60.0 / bpm * source_sample_rate / playback_rate
        strength = (
            ClickStrength.DOWNBEAT
            if pulse_index == 0
            else ClickStrength.GROUPING
            if len(grouping) > 1 and grouping[pulse_index] > 1
            else ClickStrength.BEAT
        )
        clicks.append(
            CountInClick(
                offset_frames=round(elapsed),
                strength=strength,
                phase=pulse_index + 1,
                label=f"{pulse_index + 1}",
            )
        )
        durations.append(round(duration))
        elapsed += duration
    return CountInPlan(
        mode=settings.mode,
        repetition=settings.repetition,
        available=True,
        target_source_frame=target_source_frame,
        target_musical=target,
        meter_label=f"{region.candidate.numerator}/{region.candidate.denominator}",
        grouping=grouping,
        local_quarter_bpm=bpm,
        playback_rate=playback_rate,
        bars=bars,
        beats=count_pulses,
        total_frames=total_frames,
        clicks=clicks,
        off_grid=off_grid,
    )
