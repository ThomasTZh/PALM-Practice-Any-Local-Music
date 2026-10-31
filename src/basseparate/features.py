"""Chord, key, tempo and bar/beat features from the local Vamp plugins.

The pipeline is deliberately small and inspectable:

1. hash the source and look up a content-addressed cache entry;
2. decode the recording to mono float32 at the project rate (WAV directly,
   ffmpeg for everything else or for resampling);
3. run Chordino, Key Detector and Bar and Beat Tracker in one Piper session;
4. parse the raw ``simplechord`` regions, the raw key label and the beat/bar
   lists, deriving BPM from the median beat interval;
5. write ``beats.json``, ``key.json``, ``chords.json`` and ``meta.json`` into a
   private temporary directory and rename it into the cache as one unit.

Chord labels are kept exactly as the plugin emits them (for example ``C``,
``Am``, ``C:maj`` or ``N``). Normalising them for display or for chord charts
is the UI layer's job, not the analysis layer's.

A second run on the same bytes, rate, meter and plugin parameters reads the
cache and starts no Piper process. Cancellation kills the child and no cache
entry is published; a crash can leave a hidden temporary directory but never a
half-written result.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import statistics
import subprocess
import tempfile
import time
import wave
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from basseparate.config import DEFAULT_SAMPLE_RATE
from basseparate.media import atomic_write_bytes
from basseparate.piper import (
    CancelCheck,
    FeatureMap,
    LoadedPlugin,
    PiperPaths,
    PiperSession,
    feature_label,
    feature_time,
    feature_values,
)

ANALYSIS_VERSION = 1
CHORD_OUTPUT = "simplechord"
KEY_OUTPUT = "key"
BEATS_OUTPUT = "beats"
BARS_OUTPUT = "bars"
CHORD_PLUGIN = "Chordino"
KEY_PLUGIN = "Key Detector"
BEAT_PLUGIN = "Bar and Beat Tracker"
WARM_UP_SECONDS = 2.0
TAIL_PADDING_SECONDS = 2.0
TRAILING_GUARD_SECONDS = 0.05
EDGE_TOLERANCE_SECONDS = 0.1
DECODE_TIMEOUT_SECONDS = 3600


class AnalysisError(RuntimeError):
    """The analysis pipeline failed; the message is safe for the UI."""


ProgressReporter = Callable[[float, str], None]


# ---------------------------------------------------------------------------
# value objects


@dataclass(frozen=True)
class Beat:
    time_seconds: float
    label: str | None = None


@dataclass(frozen=True)
class Bar:
    time_seconds: float
    label: str | None = None


@dataclass(frozen=True)
class BeatGrid:
    bpm: float | None
    bpb: int
    beats: tuple[Beat, ...]
    bars: tuple[Bar, ...]

    @property
    def first_beat(self) -> float | None:
        return self.beats[0].time_seconds if self.beats else None

    @property
    def bar_count(self) -> int:
        return len(self.bars)


@dataclass(frozen=True)
class KeyResult:
    label: str | None
    tonic: int | None
    mode: int | None


@dataclass(frozen=True)
class ChordRegion:
    start_seconds: float
    end_seconds: float
    label: str


@dataclass(frozen=True)
class PluginRun:
    role: str
    display_name: str
    key: str
    version: str
    parameters: Mapping[str, float]
    block_size: int
    step_size: int


@dataclass(frozen=True)
class AnalysisMeta:
    cache_key: str
    source_sha256: str
    source_name: str | None
    sample_rate: int
    duration_seconds: float
    bpb: int
    lead_in_seconds: float
    elapsed_seconds: float
    plugins: tuple[PluginRun, ...]


@dataclass(frozen=True)
class AnalysisResult:
    grid: BeatGrid
    key: KeyResult
    chords: tuple[ChordRegion, ...]
    meta: AnalysisMeta
    output_dir: Path | None
    cached: bool

    @property
    def bpm(self) -> float | None:
        return self.grid.bpm

    @property
    def key_label(self) -> str | None:
        return self.key.label

    @property
    def chord_labels(self) -> tuple[str, ...]:
        return tuple(region.label for region in self.chords)

    def write_to(self, directory: Path) -> Path:
        """Publish the four JSON documents atomically into ``directory``."""
        target = Path(directory)
        payloads = _payloads(self)
        target.mkdir(parents=True, exist_ok=True)
        for name, payload in payloads.items():
            atomic_write_bytes(target / name, payload)
        return target


# ---------------------------------------------------------------------------
# pure parsing helpers


def bpm_from_beat_times(times: Sequence[float]) -> float | None:
    """BPM from the median interval between finite beat times.

    The median makes a single missed or doubled beat harmless. Fewer than two
    usable beats means the tempo cannot be derived, so the result is ``None``
    rather than an invented number.
    """
    ordered = sorted(float(value) for value in times if math.isfinite(float(value)))
    intervals = [
        later - earlier
        for earlier, later in zip(ordered, ordered[1:], strict=False)
        if later - earlier > 1e-6
    ]
    if not intervals:
        return None
    return round(60.0 / statistics.median(intervals), 3)


def _as_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AnalysisError(f"{label} is not a JSON object")
    return value


def _as_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise AnalysisError(f"{label} is not a JSON list")
    return value


def _as_float(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnalysisError(f"{label} is not a number")
    number = float(value)
    if not math.isfinite(number):
        raise AnalysisError(f"{label} is not finite")
    return number


def _as_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AnalysisError(f"{label} is not an integer")
    return value


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _features(features: FeatureMap, output: str) -> list[Mapping[str, Any]]:
    rows = features.get(output, [])
    return [row for row in rows if isinstance(row, Mapping)]


def _trim_events(
    rows: Sequence[Mapping[str, Any]], *, lead_in_seconds: float, duration_seconds: float
) -> list[tuple[float, str | None]]:
    """Convert raw timestamps to recording time and trim edge predictions.

    The tracker can predict one event past the end and can emit a first event
    slightly before zero after a silent lead-in. Events within the last 50 ms
    are predictions rather than observations; the first event is snapped to
    zero when it is within the analysis tolerance.
    """
    events: list[tuple[float, str | None]] = []
    for row in rows:
        timestamp = feature_time(row) - lead_in_seconds
        if timestamp < -EDGE_TOLERANCE_SECONDS:
            continue
        if timestamp > duration_seconds - TRAILING_GUARD_SECONDS:
            continue
        if timestamp < 0.0:
            timestamp = 0.0
        events.append((round(timestamp, 6), feature_label(row)))
    events.sort(key=lambda item: item[0])
    deduped: list[tuple[float, str | None]] = []
    for event in events:
        if deduped and abs(event[0] - deduped[-1][0]) <= 1e-6:
            continue
        deduped.append(event)
    return deduped


def parse_grid(
    features: FeatureMap,
    *,
    bpb: int,
    duration_seconds: float,
    lead_in_seconds: float = 0.0,
) -> BeatGrid:
    """Parse ``beats`` and ``bars`` and derive the tempo from beat intervals."""
    beat_events = _trim_events(
        _features(features, BEATS_OUTPUT),
        lead_in_seconds=lead_in_seconds,
        duration_seconds=duration_seconds,
    )
    bar_events = _trim_events(
        _features(features, BARS_OUTPUT),
        lead_in_seconds=lead_in_seconds,
        duration_seconds=duration_seconds,
    )
    beats = tuple(
        Beat(time_seconds=time_seconds, label=label) for time_seconds, label in beat_events
    )
    bars = tuple(Bar(time_seconds=time_seconds, label=label) for time_seconds, label in bar_events)
    return BeatGrid(
        bpm=bpm_from_beat_times([beat.time_seconds for beat in beats]),
        bpb=bpb,
        beats=beats,
        bars=bars,
    )


def parse_key(features: FeatureMap) -> KeyResult:
    """Parse the raw key label plus tonic/mode numbers when present."""
    key_rows = _features(features, KEY_OUTPUT)
    label = feature_label(key_rows[-1]) if key_rows else None
    tonic: int | None = None
    mode: int | None = None
    for row in _features(features, "tonic"):
        values = feature_values(row)
        if values:
            tonic = int(values[0])
    for row in _features(features, "mode"):
        values = feature_values(row)
        if values:
            mode = int(values[0])
    return KeyResult(label=label, tonic=tonic, mode=mode)


def parse_chords(features: FeatureMap, *, duration_seconds: float) -> tuple[ChordRegion, ...]:
    """Turn ``simplechord`` feature points into raw-labelled regions.

    Consecutive identical labels are merged. The label is copied verbatim; no
    enharmonic spelling, case or quality normalisation happens here.
    """
    points: list[tuple[float, str]] = []
    for row in _features(features, CHORD_OUTPUT):
        label = feature_label(row)
        if label is None:
            continue
        timestamp = feature_time(row)
        if timestamp < 0.0 or timestamp > duration_seconds:
            continue
        points.append((round(timestamp, 6), label))
    points.sort(key=lambda item: item[0])
    if not points:
        return ()
    regions: list[ChordRegion] = []
    for index, (start, label) in enumerate(points):
        end = points[index + 1][0] if index + 1 < len(points) else duration_seconds
        end = min(end, duration_seconds)
        if end <= start:
            continue
        if regions and regions[-1].label == label:
            previous = regions[-1]
            regions[-1] = ChordRegion(previous.start_seconds, end, label)
        else:
            regions.append(ChordRegion(start, end, label))
    return tuple(regions)


# ---------------------------------------------------------------------------
# audio decode


def file_sha256(path: Path) -> str:
    """Stream a file through SHA-256 (used as the cache identity)."""
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _decode_wav(path: Path) -> tuple[NDArray[np.float32], int]:
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.getnframes()
            compression = handle.getcomptype()
            raw = handle.readframes(frames)
    except (wave.Error, EOFError, OSError, ValueError) as error:
        raise AnalysisError(f"cannot read WAV {path.name}: {error}") from error
    if channels < 1 or rate <= 0:
        raise AnalysisError(f"WAV {path.name} has an invalid channel count or sample rate")
    if compression != "NONE":
        raise AnalysisError(f"WAV {path.name} uses unsupported compression {compression!r}")
    if width not in (1, 2, 3, 4):
        raise AnalysisError(f"WAV {path.name} uses unsupported sample width {width} bytes")
    if width == 1:
        samples = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
        samples = (samples - 128.0) / 128.0
    elif width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        bytes_ = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        packed = bytes_[:, 0] | (bytes_[:, 1] << 8) | (bytes_[:, 2] << 16)
        signed = np.where(packed & 0x800000, packed - 0x1000000, packed)
        samples = signed.astype(np.float32) / 8_388_608.0
    else:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2_147_483_648.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1, dtype=np.float32)
    return np.ascontiguousarray(samples, dtype=np.float32), rate


def source_sample_rate(path: Path, requested: int | None) -> int:
    """The rate the analysis will actually use, before decoding samples.

    The cache key must not depend on whether the caller spelled out the native
    rate. WAV headers give the rate for free; float WAVs fall back to the
    project rate because ffmpeg does the decoding anyway.
    """
    if requested is not None:
        if requested <= 0:
            raise ValueError("sample_rate must be positive")
        return requested
    source = Path(path)
    if source.suffix.lower() == ".wav":
        try:
            with wave.open(str(source), "rb") as handle:
                rate = handle.getframerate()
        except (wave.Error, EOFError, OSError, ValueError):
            rate = 0
        if rate > 0:
            return int(rate)
    return DEFAULT_SAMPLE_RATE


def _decode_ffmpeg(path: Path, *, sample_rate: int, timeout_seconds: int) -> NDArray[np.float32]:
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise AnalysisError(
            "ffmpeg is required to decode or resample this recording but was not found "
            "on PATH; the preserved local toolchain normally provides it."
        )
    command = [
        executable,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "f32le",
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise AnalysisError(f"ffmpeg timed out decoding {path.name}") from error
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        if len(detail) > 2000:
            detail = "..." + detail[-2000:]
        raise AnalysisError(f"ffmpeg could not decode {path.name}: {detail or 'unknown error'}")
    samples = np.frombuffer(completed.stdout, dtype="<f4").astype(np.float32, copy=True)
    if samples.size == 0:
        raise AnalysisError(f"ffmpeg decoded no audio from {path.name}")
    return samples


def load_audio_mono(
    path: Path,
    *,
    sample_rate: int | None = None,
    timeout_seconds: int = DECODE_TIMEOUT_SECONDS,
) -> tuple[NDArray[np.float32], int]:
    """Decode a recording to mono float32, optionally resampling."""
    source = Path(path)
    if not source.is_file():
        raise AnalysisError(f"recording not found: {source}")
    if sample_rate is not None and sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if source.suffix.lower() == ".wav":
        try:
            samples, native_rate = _decode_wav(source)
        except AnalysisError:
            # WAVE_FORMAT_IEEE_FLOAT (3) is not readable by the standard wave
            # module; ffmpeg handles it and reports a clear error if the file
            # is actually corrupt.
            target_rate = sample_rate if sample_rate is not None else DEFAULT_SAMPLE_RATE
            return (
                _decode_ffmpeg(source, sample_rate=target_rate, timeout_seconds=timeout_seconds),
                target_rate,
            )
        if sample_rate is None or sample_rate == native_rate:
            return samples, native_rate
    target_rate = sample_rate if sample_rate is not None else DEFAULT_SAMPLE_RATE
    return _decode_ffmpeg(
        source, sample_rate=target_rate, timeout_seconds=timeout_seconds
    ), target_rate


# ---------------------------------------------------------------------------
# cache


PLUGIN_ORDER: tuple[str, ...] = (CHORD_PLUGIN, KEY_PLUGIN, BEAT_PLUGIN)


def plugin_specs(bpb: int) -> tuple[tuple[str, Mapping[str, float]], ...]:
    """The fixed plugin set and its parameter overrides."""
    return (
        (CHORD_PLUGIN, {}),
        (KEY_PLUGIN, {}),
        (BEAT_PLUGIN, {"bpb": float(bpb)}),
    )


def analysis_cache_key(
    source_sha256: str,
    *,
    sample_rate: int | None,
    bpb: int,
    lead_in_seconds: float,
    specs: Sequence[tuple[str, Mapping[str, float]]],
) -> str:
    """Content address: source bytes, rate, meter and plugin parameters."""
    identity = {
        "schema": ANALYSIS_VERSION,
        "source_sha256": source_sha256,
        "sample_rate": sample_rate if sample_rate is not None else "native",
        "bpb": bpb,
        "lead_in_seconds": round(lead_in_seconds, 6),
        "plugins": [
            {"display_name": name, "parameters": dict(sorted(parameters.items()))}
            for name, parameters in specs
        ],
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _grid_payload(
    grid: BeatGrid, *, source_sha256: str, sample_rate: int, lead_in_seconds: float
) -> dict[str, object]:
    return {
        "version": ANALYSIS_VERSION,
        "source_sha256": source_sha256,
        "sample_rate": sample_rate,
        "bpb": grid.bpb,
        "lead_in_seconds": lead_in_seconds,
        "bpm": grid.bpm,
        "first_beat_seconds": grid.first_beat,
        "bar_count": grid.bar_count,
        "beats": [{"time_seconds": beat.time_seconds, "label": beat.label} for beat in grid.beats],
        "bars": [{"time_seconds": bar.time_seconds, "label": bar.label} for bar in grid.bars],
    }


def _key_payload(key: KeyResult, *, source_sha256: str) -> dict[str, object]:
    return {
        "version": ANALYSIS_VERSION,
        "source_sha256": source_sha256,
        "label": key.label,
        "tonic": key.tonic,
        "mode": key.mode,
        "normalised": False,
    }


def _chords_payload(
    chords: Sequence[ChordRegion], *, source_sha256: str, duration_seconds: float
) -> dict[str, object]:
    return {
        "version": ANALYSIS_VERSION,
        "source_sha256": source_sha256,
        "duration_seconds": duration_seconds,
        "labels_raw": True,
        "chords": [
            {
                "start_seconds": chord.start_seconds,
                "end_seconds": chord.end_seconds,
                "label": chord.label,
            }
            for chord in chords
        ],
    }


def _meta_payload(meta: AnalysisMeta) -> dict[str, object]:
    return {
        "version": ANALYSIS_VERSION,
        "cache_key": meta.cache_key,
        "source_sha256": meta.source_sha256,
        "source_name": meta.source_name,
        "sample_rate": meta.sample_rate,
        "duration_seconds": meta.duration_seconds,
        "bpb": meta.bpb,
        "lead_in_seconds": meta.lead_in_seconds,
        "elapsed_seconds": meta.elapsed_seconds,
        "labels_raw": True,
        "plugins": [
            {
                "role": run.role,
                "display_name": run.display_name,
                "key": run.key,
                "version": run.version,
                "parameters": dict(sorted(run.parameters.items())),
                "block_size": run.block_size,
                "step_size": run.step_size,
            }
            for run in meta.plugins
        ],
    }


def _payloads(result: AnalysisResult) -> dict[str, bytes]:
    return {
        "beats.json": _json_bytes(
            _grid_payload(
                result.grid,
                source_sha256=result.meta.source_sha256,
                sample_rate=result.meta.sample_rate,
                lead_in_seconds=result.meta.lead_in_seconds,
            )
        ),
        "key.json": _json_bytes(_key_payload(result.key, source_sha256=result.meta.source_sha256)),
        "chords.json": _json_bytes(
            _chords_payload(
                result.chords,
                source_sha256=result.meta.source_sha256,
                duration_seconds=result.meta.duration_seconds,
            )
        ),
        "meta.json": _json_bytes(_meta_payload(result.meta)),
    }


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AnalysisError(f"cache file {path.name} is unreadable: {error}") from error
    return _as_mapping(payload, path.name)


def _grid_from_payload(payload: Mapping[str, Any]) -> BeatGrid:
    beats = tuple(
        Beat(
            time_seconds=_as_float(_as_mapping(row, "beat")["time_seconds"], "beat time"),
            label=_optional_str(_as_mapping(row, "beat").get("label")),
        )
        for row in _as_list(payload.get("beats"), "beats")
    )
    bars = tuple(
        Bar(
            time_seconds=_as_float(_as_mapping(row, "bar")["time_seconds"], "bar time"),
            label=_optional_str(_as_mapping(row, "bar").get("label")),
        )
        for row in _as_list(payload.get("bars"), "bars")
    )
    bpm = payload.get("bpm")
    return BeatGrid(
        bpm=None if bpm is None else _as_float(bpm, "bpm"),
        bpb=_as_int(payload.get("bpb"), "bpb"),
        beats=beats,
        bars=bars,
    )


def _key_from_payload(payload: Mapping[str, Any]) -> KeyResult:
    tonic = payload.get("tonic")
    mode = payload.get("mode")
    return KeyResult(
        label=_optional_str(payload.get("label")),
        tonic=None if tonic is None else _as_int(tonic, "tonic"),
        mode=None if mode is None else _as_int(mode, "mode"),
    )


def _chords_from_payload(payload: Mapping[str, Any]) -> tuple[ChordRegion, ...]:
    regions: list[ChordRegion] = []
    for row in _as_list(payload.get("chords"), "chords"):
        entry = _as_mapping(row, "chord")
        label = entry.get("label")
        if not isinstance(label, str):
            raise AnalysisError("cached chord has no raw label")
        regions.append(
            ChordRegion(
                start_seconds=_as_float(entry.get("start_seconds"), "chord start"),
                end_seconds=_as_float(entry.get("end_seconds"), "chord end"),
                label=label,
            )
        )
    return tuple(regions)


def _meta_from_payload(payload: Mapping[str, Any], *, output_dir: Path) -> AnalysisMeta:
    runs: list[PluginRun] = []
    for row in _as_list(payload.get("plugins"), "plugins"):
        entry = _as_mapping(row, "plugin")
        parameters = _as_mapping(entry.get("parameters"), "plugin parameters")
        runs.append(
            PluginRun(
                role=str(entry.get("role", "")),
                display_name=str(entry.get("display_name", "")),
                key=str(entry.get("key", "")),
                version=str(entry.get("version", "")),
                parameters={
                    name: _as_float(value, f"parameter {name}")
                    for name, value in parameters.items()
                },
                block_size=_as_int(entry.get("block_size"), "block size"),
                step_size=_as_int(entry.get("step_size"), "step size"),
            )
        )
    return AnalysisMeta(
        cache_key=str(payload.get("cache_key", output_dir.name)),
        source_sha256=str(payload.get("source_sha256", "")),
        source_name=_optional_str(payload.get("source_name")),
        sample_rate=_as_int(payload.get("sample_rate"), "sample rate"),
        duration_seconds=_as_float(payload.get("duration_seconds"), "duration"),
        bpb=_as_int(payload.get("bpb"), "bpb"),
        lead_in_seconds=_as_float(payload.get("lead_in_seconds"), "lead-in"),
        elapsed_seconds=_as_float(payload.get("elapsed_seconds"), "elapsed"),
        plugins=tuple(runs),
    )


def read_cache(cache_dir: Path, key: str) -> AnalysisResult | None:
    """Read a complete cache entry, or return ``None`` if it is absent/corrupt."""
    entry = Path(cache_dir) / key
    try:
        grid = _grid_from_payload(_read_json(entry / "beats.json"))
        key_result = _key_from_payload(_read_json(entry / "key.json"))
        chords = _chords_from_payload(_read_json(entry / "chords.json"))
        meta = _meta_from_payload(_read_json(entry / "meta.json"), output_dir=entry)
    except (AnalysisError, KeyError, TypeError, ValueError):
        return None
    return AnalysisResult(
        grid=grid,
        key=key_result,
        chords=chords,
        meta=meta,
        output_dir=entry,
        cached=True,
    )


def write_cache(cache_dir: Path, result: AnalysisResult) -> Path:
    """Publish all four documents by renaming one private directory."""
    directory = Path(cache_dir)
    final = directory / result.meta.cache_key
    if final.is_dir():
        if read_cache(directory, result.meta.cache_key) is not None:
            return final
        shutil.rmtree(final, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{result.meta.cache_key}.", dir=directory))
    try:
        for name, payload in _payloads(result).items():
            atomic_write_bytes(temporary / name, payload)
        try:
            temporary.rename(final)
        except OSError:
            if not final.is_dir():
                raise
            shutil.rmtree(temporary, ignore_errors=True)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


# ---------------------------------------------------------------------------
# pipeline


def _effective_lead_in(requested: float | None) -> float:
    """The explicit lead-in, or zero.

    Short clips (the four-second click fixture, for example) need a silent
    lead-in *and* a short tail for the tracker to place a downbeat. Callers
    request that explicitly with ``lead_in_seconds=WARM_UP_SECONDS``; the
    default analyses exactly the recording, which keeps the cache identity
    independent of the recording length.
    """
    if requested is None:
        return 0.0
    if requested < 0:
        raise ValueError("lead_in_seconds must not be negative")
    return requested


def _run_plugins(
    signal: NDArray[np.float32],
    *,
    sample_rate: int,
    lead_in_seconds: float,
    bpb: int,
    paths: PiperPaths,
    timeout_seconds: float,
    is_cancelled: CancelCheck | None,
    on_progress: ProgressReporter | None,
) -> tuple[list[tuple[str, LoadedPlugin, FeatureMap]], float]:
    specs = plugin_specs(bpb)
    order = {name: index for index, (name, _) in enumerate(specs)}
    warm_up_frames = int(round(lead_in_seconds * sample_rate))
    beat_signal = signal
    if warm_up_frames > 0:
        # Both edges need context: the tracker only decides on a downbeat once
        # it has seen enough following audio. The padding is removed again by
        # ``parse_grid`` (timestamps shifted, events past the end trimmed).
        lead = np.zeros(warm_up_frames, dtype=np.float32)
        tail = np.zeros(int(round(TAIL_PADDING_SECONDS * sample_rate)), dtype=np.float32)
        beat_signal = np.concatenate((lead, signal, tail))
    signals = {CHORD_PLUGIN: signal, KEY_PLUGIN: signal, BEAT_PLUGIN: beat_signal}

    def report(display_name: str, processed: int, total: int) -> None:
        if on_progress is None:
            return
        index = order.get(display_name, 0)
        fraction = (processed / total) if total > 0 else 1.0
        overall = (index + fraction) / len(specs)
        on_progress(min(1.0, max(0.0, overall)), display_name)

    started = time.perf_counter()
    runs: list[tuple[str, LoadedPlugin, FeatureMap]] = []
    with PiperSession(
        paths,
        timeout_seconds=timeout_seconds,
        is_cancelled=is_cancelled,
        on_progress=report,
    ) as session:
        for display_name, parameters in specs:
            plugin, features = session.analyze(
                display_name,
                signals[display_name],
                sample_rate=sample_rate,
                parameters=parameters,
            )
            runs.append((display_name, plugin, features))
    return runs, time.perf_counter() - started


def analyze_signal(
    signal: NDArray[np.float32],
    *,
    sample_rate: int,
    source_sha256: str,
    cache_dir: Path | None = None,
    bpb: int = 4,
    lead_in_seconds: float | None = None,
    piper_paths: PiperPaths | None = None,
    timeout_seconds: float = 600.0,
    is_cancelled: CancelCheck | None = None,
    on_progress: ProgressReporter | None = None,
    force: bool = False,
    source_name: str | None = None,
) -> AnalysisResult:
    """Analyse an already decoded mono signal."""
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if not 2 <= bpb <= 16:
        raise ValueError("bpb must be between 2 and 16")
    if signal.ndim != 1:
        raise ValueError("signal must be mono")
    if int(signal.shape[0]) < 1:
        raise AnalysisError("the recording contains no audio frames")
    duration_seconds = float(signal.shape[0]) / sample_rate
    lead_in = _effective_lead_in(lead_in_seconds)
    specs = plugin_specs(bpb)
    key = analysis_cache_key(
        source_sha256,
        sample_rate=sample_rate,
        bpb=bpb,
        lead_in_seconds=lead_in,
        specs=specs,
    )
    if cache_dir is not None and not force:
        cached = read_cache(cache_dir, key)
        if cached is not None:
            return cached
    paths = piper_paths or PiperPaths.for_project()
    runs, elapsed = _run_plugins(
        signal,
        sample_rate=sample_rate,
        lead_in_seconds=lead_in,
        bpb=bpb,
        paths=paths,
        timeout_seconds=timeout_seconds,
        is_cancelled=is_cancelled,
        on_progress=on_progress,
    )
    by_name = {name: features for name, _, features in runs}
    grid = parse_grid(
        by_name[BEAT_PLUGIN],
        bpb=bpb,
        duration_seconds=duration_seconds,
        lead_in_seconds=lead_in,
    )
    key_result = parse_key(by_name[KEY_PLUGIN])
    chords = parse_chords(by_name[CHORD_PLUGIN], duration_seconds=duration_seconds)
    meta = AnalysisMeta(
        cache_key=key,
        source_sha256=source_sha256,
        source_name=source_name,
        sample_rate=sample_rate,
        duration_seconds=duration_seconds,
        bpb=bpb,
        lead_in_seconds=lead_in,
        elapsed_seconds=round(elapsed, 6),
        plugins=tuple(
            PluginRun(
                role=name,
                display_name=plugin.display_name,
                key=plugin.key,
                version=plugin.version,
                parameters=plugin.parameters,
                block_size=plugin.block_size,
                step_size=plugin.step_size,
            )
            for name, plugin, _ in runs
        ),
    )
    result = AnalysisResult(
        grid=grid,
        key=key_result,
        chords=chords,
        meta=meta,
        output_dir=None,
        cached=False,
    )
    if cache_dir is not None:
        output_dir = write_cache(cache_dir, result)
        result = AnalysisResult(
            grid=grid,
            key=key_result,
            chords=chords,
            meta=meta,
            output_dir=output_dir,
            cached=False,
        )
    return result


def analyze_file(
    source: Path,
    *,
    cache_dir: Path | None = None,
    sample_rate: int | None = None,
    bpb: int = 4,
    lead_in_seconds: float | None = None,
    piper_paths: PiperPaths | None = None,
    timeout_seconds: float = 600.0,
    is_cancelled: CancelCheck | None = None,
    on_progress: ProgressReporter | None = None,
    force: bool = False,
) -> AnalysisResult:
    """Analyse a recording, reusing a complete content-addressed cache entry."""
    path = Path(source)
    if not path.is_file():
        raise AnalysisError(f"recording not found: {path}")
    digest = file_sha256(path)
    lead_in = _effective_lead_in(lead_in_seconds)
    rate = source_sample_rate(path, sample_rate)
    if cache_dir is not None and not force:
        key = analysis_cache_key(
            digest,
            sample_rate=rate,
            bpb=bpb,
            lead_in_seconds=lead_in,
            specs=plugin_specs(bpb),
        )
        cached = read_cache(cache_dir, key)
        if cached is not None:
            return cached
    signal, decoded_rate = load_audio_mono(path, sample_rate=rate)
    if decoded_rate != rate:
        raise AnalysisError(
            f"decoded {path.name} at {decoded_rate} Hz but the analysis requested {rate} Hz"
        )
    return analyze_signal(
        signal,
        sample_rate=rate,
        source_sha256=digest,
        cache_dir=cache_dir,
        bpb=bpb,
        lead_in_seconds=lead_in_seconds,
        piper_paths=piper_paths,
        timeout_seconds=timeout_seconds,
        is_cancelled=is_cancelled,
        on_progress=on_progress,
        force=force,
        source_name=path.name,
    )
