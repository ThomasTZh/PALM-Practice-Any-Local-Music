"""Sonic Annotator 1.7 backend for Linux.

Gate 0 uses the official Linux static Sonic Annotator and the preserved Vamp
plugins. Plugin ids are discovered with ``--list``; only semantic plugin names
(Chordino, QM Key Detector, QM Bar and Beat Tracker) are fixed. The backend
writes 32-bit float mono WAVs and invokes Sonic Annotator with argument lists
and CSV output, so paths containing spaces or non-ASCII characters are safe.

Piper runs Chordino/Key Detector on the unpadded signal and the beat tracker on
a signal with the requested lead-in and a 2 s tail. This backend preserves that
shape: ``signal.wav`` is unpadded, ``beats.wav`` has the same padding. Beat
timestamps therefore include the lead-in; features.parse_grid subtracts it.
"""

from __future__ import annotations

import csv
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from basseparate.analysis_backend import (
    TAIL_PADDING_SECONDS,
    AnalysisBackendError,
    BackendPlugin,
    BackendResult,
    ProgressReporter,
)
from basseparate.config import runtime_paths
from basseparate.features import (
    BARS_OUTPUT,
    BEAT_PLUGIN,
    BEATS_OUTPUT,
    CHORD_OUTPUT,
    CHORD_PLUGIN,
    KEY_OUTPUT,
    KEY_PLUGIN,
)
from basseparate.piper import CancelCheck

SONIC_BACKEND_ID = "sonic"
SONIC_BACKEND_VERSION = "1.7"
SONIC_BINARY_NAME = "sonic-annotator"
SONIC_EXTRACTED_RELATIVE = Path("sonic-annotator-1.7.0") / "squashfs-root" / "AppRun"
CHORDINO_BOOSTN = 0.2
POLL_SECONDS = 0.02
TERMINATION_GRACE_SECONDS = 1.0
STDERR_TAIL_BYTES = 4000


class SonicAnnotatorError(AnalysisBackendError):
    """Sonic Annotator could not complete an analysis."""


class SonicAnnotatorUnavailable(SonicAnnotatorError):
    """The Sonic Annotator binary is missing or not executable."""


class SonicPluginError(SonicAnnotatorError):
    """A required Vamp plugin/output is missing from --list."""


class SonicCommandError(SonicAnnotatorError):
    """Sonic Annotator exited non-zero."""


class SonicTimeout(SonicAnnotatorError):
    """A Sonic Annotator invocation exceeded its timeout."""


class SonicCancelled(SonicAnnotatorError):
    """The caller cancelled the analysis."""


class SonicParseError(SonicAnnotatorError):
    """A Sonic Annotator CSV file was malformed."""


@dataclass(frozen=True)
class SonicPlugin:
    """A transform id resolved from ``sonic-annotator --list``."""

    library: str
    plugin: str
    output: str

    @property
    def transform(self) -> str:
        return f"vamp:{self.library}:{self.plugin}:{self.output}"


@dataclass(frozen=True)
class ResolvedPlugins:
    chord: SonicPlugin
    key: SonicPlugin
    beats: SonicPlugin
    bars: SonicPlugin
    key_tonic: SonicPlugin | None = None
    key_mode: SonicPlugin | None = None


@dataclass(frozen=True)
class CsvFeature:
    time_seconds: float
    label: str
    values: tuple[float, ...] = ()


def _timestamp(seconds: float) -> dict[str, int]:
    whole = int(seconds)
    return {"s": whole, "n": int(round((seconds - whole) * 1_000_000_000))}


def _parse_time(value: str, *, path: Path, line: int) -> float:
    try:
        number = float(value.strip())
    except ValueError as error:
        raise SonicParseError(f"{path.name} line {line}: invalid time {value!r}") from error
    if not np.isfinite(number) or number < 0:
        raise SonicParseError(f"{path.name} line {line}: invalid time {value!r}")
    return number


def _header_map(row: Sequence[str]) -> dict[str, int] | None:
    names = [cell.strip().lower() for cell in row]
    if not any(name in {"time", "timestamp", "start", "start_time"} for name in names):
        return None
    mapping: dict[str, int] = {}
    for index, name in enumerate(names):
        if name in {"time", "timestamp", "start", "start_time"}:
            mapping.setdefault("time", index)
        elif name in {"duration", "end", "end_time"}:
            mapping.setdefault("duration", index)
        elif name in {"label", "value"}:
            mapping.setdefault("label", index)
        elif name in {"values", "value", "feature", "features"}:
            mapping.setdefault("values", index)
        elif name in {"filename", "file", "audio"}:
            mapping.setdefault("filename", index)
    if "time" not in mapping or "label" not in mapping:
        raise SonicParseError("CSV header must contain a time column and a label/value column")
    return mapping


def parse_csv_features(
    path: Path,
    *,
    default_columns: Sequence[str] = ("time", "label"),
) -> list[CsvFeature]:
    """Parse Sonic CSV output by header when present, else by known columns.

    Sonic 1.7 does not emit a header. A header is still accepted (and is used
    by the tests/future transforms) when its first cell is textual. Without a
    header the column count selects the documented layout: time,label for
    chord/beat outputs and time,values,label for key output.
    """
    source = Path(path)
    try:
        with source.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
    except (OSError, UnicodeDecodeError) as error:
        raise SonicParseError(f"cannot read CSV {source.name}: {error}") from error
    if not rows:
        return []
    header: dict[str, int] | None = None
    first = rows[0]
    if first and not _looks_numeric(first[0]):
        header = _header_map(first)
        if header is None:
            raise SonicParseError(f"{source.name}: unrecognized header {first!r}")
        rows = rows[1:]
    parsed: list[CsvFeature] = []
    for line_number, row in enumerate(rows, start=2 if header else 1):
        if not any(cell.strip() for cell in row):
            continue
        if header is not None:
            time_index = header["time"]
            label_index = header["label"]
            value_indexes = [index for key, index in header.items() if key in {"values"}]
            if not value_indexes:
                start = time_index + 1
                value_indexes = list(range(start, label_index))
        else:
            columns = list(default_columns)
            if len(row) == len(columns) + 1 and not _looks_numeric(row[0]):
                columns = ["filename", *columns]
            if len(row) != len(columns):
                raise SonicParseError(
                    f"{source.name} line {line_number}: expected {len(columns)} columns, "
                    f"found {len(row)}"
                )
            mapping = {name: index for index, name in enumerate(columns)}
            time_index = mapping["time"]
            label_index = mapping["label"]
            value_indexes = [index for index, name in enumerate(columns) if name == "values"]
        if not 0 <= time_index < len(row) or not 0 <= label_index < len(row):
            raise SonicParseError(f"{source.name} line {line_number}: missing column")
        time_seconds = _parse_time(row[time_index], path=source, line=line_number)
        label = row[label_index].strip()
        if not label:
            raise SonicParseError(f"{source.name} line {line_number}: empty label")
        values: list[float] = []
        for index in value_indexes:
            if index >= len(row):
                raise SonicParseError(f"{source.name} line {line_number}: missing value")
            try:
                values.append(float(row[index]))
            except ValueError as error:
                raise SonicParseError(
                    f"{source.name} line {line_number}: invalid value {row[index]!r}"
                ) from error
        parsed.append(CsvFeature(time_seconds=time_seconds, label=label, values=tuple(values)))
    return parsed


def _looks_numeric(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def write_float_wav(path: Path, signal: NDArray[np.float32], sample_rate: int) -> None:
    """Write a mono IEEE-float 32-bit WAV without external dependencies."""
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    samples = np.ascontiguousarray(signal, dtype="<f4")
    data = samples.tobytes()
    fmt = struct.pack(
        "<HHIIHH",
        3,  # WAVE_FORMAT_IEEE_FLOAT
        1,
        sample_rate,
        sample_rate * 4,
        4,
        32,
    )
    header = (
        struct.pack("<4sI4s", b"RIFF", 36 + len(data), b"WAVE")
        + struct.pack("<4sI", b"fmt ", len(fmt))
        + fmt
        + struct.pack("<4sI", b"data", len(data))
    )
    Path(path).write_bytes(header + data)


class SonicAnnotatorBackend:
    """Sonic Annotator + Vamp backend for Linux, Windows and macOS."""

    id = SONIC_BACKEND_ID
    version = SONIC_BACKEND_VERSION

    def __init__(
        self,
        *,
        binary: Path | None = None,
        plugin_paths: Sequence[Path] | None = None,
        timeout_seconds: float = 600.0,
        tmp_root: Path | None = None,
    ) -> None:
        runtime = runtime_paths()
        tools_root = runtime.tools_root
        self.tools_root = tools_root
        bundled_tools = runtime.app_root / "tools"
        platform = f"{sys.platform}"
        default_plugin_paths: tuple[Path, ...]
        if platform.startswith("win"):
            default_binary = bundled_tools / "sonic-annotator" / "sonic-annotator.exe"
            if not default_binary.is_file():
                default_binary = tools_root / "sonic-annotator-1.7.0" / "sonic-annotator.exe"
            default_plugin_paths = (
                bundled_tools / "vamp-plugins",
                tools_root / "vamp-plugins",
            )
        elif platform.startswith("darwin"):
            default_binary = tools_root / "sonic-annotator-1.7.0" / "sonic-annotator"
            default_plugin_paths = (tools_root / "vamp-plugins",)
        else:
            default_binary = tools_root / SONIC_EXTRACTED_RELATIVE
            default_plugin_paths = (
                tools_root / "vamp-plugins",
                tools_root / "plugins",
            )
        self.binary = (
            Path(binary)
            if binary is not None
            else Path(os.environ.get("BASSEPARATE_SONIC_ANNOTATOR", default_binary))
        )
        if plugin_paths is None:
            plugin_paths = default_plugin_paths
        paths = [Path(item) for item in plugin_paths]
        for item in os.environ.get("VAMP_PATH", "").split(os.pathsep):
            if item:
                paths.append(Path(item))
        self.plugin_paths = tuple(dict.fromkeys(paths))
        self.timeout_seconds = timeout_seconds
        self.tmp_root = Path(tmp_root) if tmp_root is not None else None
        if self.tmp_root is not None:
            self.tmp_root.mkdir(parents=True, exist_ok=True)
        # Sonic Annotator writes a QMUL debug log under HOME. A read-only or
        # missing home directory can crash the static build with a buffer
        # overflow, so give each backend a writable session home.
        self._home_dir = tempfile.TemporaryDirectory(prefix="palm-sonic-home-", dir=self.tmp_root)
        self._home = Path(self._home_dir.name)
        (self._home / ".local" / "share" / "QMUL" / "Sonic Annotator" / "log").mkdir(
            parents=True, exist_ok=True
        )
        (self._home / "Library" / "Application Support" / "QMUL" / "Sonic Annotator" / "log").mkdir(
            parents=True, exist_ok=True
        )
        for appdata in ("Roaming", "Local"):
            (self._home / "AppData" / appdata / "QMUL" / "Sonic Annotator" / "log").mkdir(
                parents=True, exist_ok=True
            )
        self._resolved: ResolvedPlugins | None = None
        self._versions: dict[str, str] = {}

    @property
    def cache_identity(self) -> str:
        return f"{self.id}:{self.version}"

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["VAMP_PATH"] = os.pathsep.join(str(path) for path in self.plugin_paths)
        env["HOME"] = str(self._home)
        env["XDG_DATA_HOME"] = str(self._home / ".local" / "share")
        env["APPDATA"] = str(self._home / "AppData" / "Roaming")
        env["LOCALAPPDATA"] = str(self._home / "AppData" / "Local")
        return env

    def close(self) -> None:
        self._home_dir.cleanup()

    def _check_binary(self) -> None:
        if not self.binary.is_file():
            raise SonicAnnotatorUnavailable(
                f"Sonic Annotator is not installed at {self.binary}. Install "
                f"'Sonic Annotator' and 'Vamp Plugin Pack' with PALM Setup under "
                f"{self.tools_root}."
            )
        if not os.access(self.binary, os.X_OK):
            raise SonicAnnotatorUnavailable(f"Sonic Annotator is not executable: {self.binary}")

    def discover_plugins(self) -> ResolvedPlugins:
        """Run ``sonic-annotator --list`` and resolve the four transforms."""
        if self._resolved is not None:
            return self._resolved
        self._check_binary()
        try:
            result = subprocess.run(
                [str(self.binary), "--list"],
                capture_output=True,
                text=True,
                env=self._env(),
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise SonicTimeout("sonic-annotator --list timed out") from error
        if result.returncode != 0:
            raise SonicCommandError(
                f"sonic-annotator --list failed: {_tail(result.stderr) or 'unknown error'}"
            )
        available: list[SonicPlugin] = []
        for line in result.stdout.splitlines():
            parts = line.strip().split(":")
            if len(parts) >= 4 and parts[0] == "vamp":
                available.append(SonicPlugin(parts[1], parts[2], parts[3]))
        if not available:
            raise SonicPluginError("sonic-annotator --list returned no Vamp transforms")
        chord = _choose(available, "chordino", "simplechord")
        key = _choose(available, "qm-keydetector", "key")
        beats = _choose(available, "qm-barbeattracker", "beats")
        bars = _choose(available, "qm-barbeattracker", "bars")
        key_tonic = _choose(available, "qm-keydetector", "tonic")
        key_mode = _choose(available, "qm-keydetector", "mode")
        if chord is None or key is None or beats is None or bars is None:
            missing = [
                name
                for name, plugin in (
                    ("chordino:simplechord", chord),
                    ("qm-keydetector:key", key),
                    ("qm-barbeattracker:beats", beats),
                    ("qm-barbeattracker:bars", bars),
                )
                if plugin is None
            ]
            raise SonicPluginError(
                "required Vamp plugins are missing from sonic-annotator --list: "
                + ", ".join(missing)
                + f". Install 'Vamp Plugin Pack' with PALM Setup under {self.tools_root}."
            )
        self._resolved = ResolvedPlugins(
            chord=chord,
            key=key,
            beats=beats,
            bars=bars,
            key_tonic=key_tonic,
            key_mode=key_mode,
        )
        return self._resolved

    def plugin_version(self, plugin: SonicPlugin) -> str:
        """Query the actual Vamp plugin version from a Sonic skeleton transform."""
        cached = self._versions.get(plugin.transform)
        if cached is not None:
            return cached
        try:
            result = subprocess.run(
                [str(self.binary), "-s", plugin.transform],
                capture_output=True,
                text=True,
                env=self._env(),
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            self._versions[plugin.transform] = "unknown"
            return "unknown"
        version = "unknown"
        if result.returncode == 0:
            match = re.search(r'vamp:plugin_version\s+"""([^"]+)"""', result.stdout)
            if match is not None:
                version = match.group(1)
        self._versions[plugin.transform] = version
        return version

    def _run(
        self,
        plugin: SonicPlugin,
        audio: Path,
        output: Path,
        *,
        is_cancelled: CancelCheck | None,
        stage: str,
        on_progress: ProgressReporter | None,
        fraction: float,
        transform_path: Path | None = None,
    ) -> None:
        transform_args = (
            ["-t", str(transform_path)] if transform_path is not None else ["-d", plugin.transform]
        )
        command = [
            str(self.binary),
            "-q",
            *transform_args,
            "-w",
            "csv",
            "--csv-one-file",
            str(output),
            "--csv-omit-filename",
            "--csv-force",
            str(audio),
        ]
        if on_progress is not None:
            on_progress(fraction, stage)
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(
                command,
                stdout=stdout,
                stderr=stderr,
                env=self._env(),
                shell=False,
            )
            deadline = time.monotonic() + self.timeout_seconds
            while process.poll() is None:
                if is_cancelled is not None and is_cancelled():
                    _terminate(process)
                    raise SonicCancelled(f"cancelled while running {plugin.transform}")
                if time.monotonic() >= deadline:
                    _terminate(process)
                    raise SonicTimeout(
                        f"timed out after {self.timeout_seconds:.0f}s running {plugin.transform}"
                    )
                time.sleep(POLL_SECONDS)
            stdout.seek(0)
            stderr.seek(0)
            detail = _tail(stderr.read().decode("utf-8", "replace"))
        if process.returncode != 0:
            raise SonicCommandError(
                f"sonic-annotator failed for {plugin.transform}: "
                f"{detail or f'exit {process.returncode}'}"
            )

    def analyze(
        self,
        signal: NDArray[np.float32],
        *,
        sample_rate: int,
        bpb: int,
        lead_in_seconds: float,
        specs: Sequence[tuple[str, Mapping[str, float]]],
        is_cancelled: CancelCheck | None = None,
        on_progress: ProgressReporter | None = None,
    ) -> BackendResult:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if signal.ndim != 1 or signal.size == 0:
            raise SonicAnnotatorError("Sonic Annotator requires a non-empty mono signal")
        resolved = self.discover_plugins()
        started = time.perf_counter()
        if on_progress is not None:
            on_progress(0.05, "Sonic Annotator: preparing audio")
        with tempfile.TemporaryDirectory(prefix="palm-sonic-", dir=self.tmp_root) as directory:
            root = Path(directory)
            signal_path = root / "signal.wav"
            beats_path = root / "beats.wav"
            write_float_wav(signal_path, signal, sample_rate)
            beat_signal = signal
            if lead_in_seconds > 0:
                lead = np.zeros(int(round(lead_in_seconds * sample_rate)), dtype=np.float32)
                tail = np.zeros(int(round(TAIL_PADDING_SECONDS * sample_rate)), dtype=np.float32)
                beat_signal = np.concatenate((lead, signal, tail))
            write_float_wav(beats_path, beat_signal, sample_rate)
            chord_ttl = root / "chordino.ttl"
            chord_ttl.write_text(
                _chordino_transform(self.plugin_version(resolved.chord), resolved.chord.library),
                encoding="utf-8",
            )
            csv_paths = {
                "chord": root / "chord.csv",
                "key": root / "key.csv",
                "beats": root / "beats.csv",
                "bars": root / "bars.csv",
                "tonic": root / "tonic.csv",
                "mode": root / "mode.csv",
            }
            self._run(
                resolved.chord,
                signal_path,
                csv_paths["chord"],
                is_cancelled=is_cancelled,
                stage="Sonic Annotator: Chordino",
                on_progress=on_progress,
                fraction=0.2,
                transform_path=chord_ttl,
            )
            self._run(
                resolved.key,
                signal_path,
                csv_paths["key"],
                is_cancelled=is_cancelled,
                stage="Sonic Annotator: key",
                on_progress=on_progress,
                fraction=0.4,
            )
            key_rows = parse_csv_features(
                csv_paths["key"], default_columns=("time", "values", "label")
            )
            key_feature_map: dict[str, list[dict[str, object]]] = {
                KEY_OUTPUT: [_row(row) for row in key_rows]
            }
            if resolved.key_tonic is not None:
                self._run(
                    resolved.key_tonic,
                    signal_path,
                    csv_paths["tonic"],
                    is_cancelled=is_cancelled,
                    stage="Sonic Annotator: key tonic",
                    on_progress=on_progress,
                    fraction=0.45,
                )
                tonic_rows = parse_csv_features(
                    csv_paths["tonic"], default_columns=("time", "values", "label")
                )
                key_feature_map["tonic"] = [_row(row) for row in tonic_rows]
            if resolved.key_mode is not None:
                self._run(
                    resolved.key_mode,
                    signal_path,
                    csv_paths["mode"],
                    is_cancelled=is_cancelled,
                    stage="Sonic Annotator: key mode",
                    on_progress=on_progress,
                    fraction=0.5,
                )
                mode_rows = parse_csv_features(
                    csv_paths["mode"], default_columns=("time", "values", "label")
                )
                key_feature_map["mode"] = [_row(row) for row in mode_rows]
            self._run(
                resolved.beats,
                beats_path,
                csv_paths["beats"],
                is_cancelled=is_cancelled,
                stage="Sonic Annotator: beats",
                on_progress=on_progress,
                fraction=0.6,
            )
            self._run(
                resolved.bars,
                beats_path,
                csv_paths["bars"],
                is_cancelled=is_cancelled,
                stage="Sonic Annotator: bars",
                on_progress=on_progress,
                fraction=0.8,
            )
            if on_progress is not None:
                on_progress(0.9, "Sonic Annotator: parsing CSV")
            chord_rows = _drop_terminal_no_chord(
                parse_csv_features(csv_paths["chord"], default_columns=("time", "label"))
            )
            beat_rows = parse_csv_features(csv_paths["beats"], default_columns=("time", "label"))
            bar_rows = parse_csv_features(csv_paths["bars"], default_columns=("time", "label"))
        return BackendResult(
            features={
                CHORD_PLUGIN: {CHORD_OUTPUT: [_row(row) for row in chord_rows]},
                KEY_PLUGIN: key_feature_map,
                BEAT_PLUGIN: {
                    BEATS_OUTPUT: [_row(row) for row in beat_rows],
                    BARS_OUTPUT: [_row(row) for row in bar_rows],
                },
            },
            plugins=(
                _plugin(
                    CHORD_PLUGIN,
                    "Chordino",
                    resolved.chord,
                    version=self.plugin_version(resolved.chord),
                ),
                _plugin(
                    KEY_PLUGIN,
                    "QM Key Detector",
                    resolved.key,
                    version=self.plugin_version(resolved.key),
                ),
                _plugin(
                    BEAT_PLUGIN,
                    "QM Bar and Beat Tracker",
                    resolved.beats,
                    version=self.plugin_version(resolved.beats),
                    bpb=bpb,
                ),
            ),
            elapsed_seconds=time.perf_counter() - started,
        )


def _drop_terminal_no_chord(rows: list[CsvFeature]) -> list[CsvFeature]:
    """Drop Sonic's EOF no-chord marker, preserving leading/interior N rows.

    Sonic Chordino writes one extra N at the end of the file on every synthetic
    fixture; the Piper host does not. A lone N, a leading N and a genuine
    interior N are preserved. This is the documented N normalization used by
    the parity test.
    """
    if len(rows) >= 2 and rows[-1].label == "N":
        return rows[:-1]
    return rows


def _chordino_transform(version: str, library: str) -> str:
    """A Chordino transform calibrated to the Piper host on the fixtures.

    Sonic's default boostn=0.1 reports an Fmaj7 for the click fixture while the
    Piper host reports only N. boostn=0.2 suppresses that click artifact and
    leaves the genuine C/Am/F/G progressions unchanged.
    """
    version_line = f'    vamp:plugin_version """{version}""" ;\n' if version != "unknown" else ""
    bindings = (
        ("boostn", CHORDINO_BOOSTN),
        ("rollon", 0.0),
        ("s", 0.7),
        ("tuningmode", 0.0),
        ("useNNLS", 1.0),
        ("usehartesyntax", 0.0),
        ("whitening", 1.0),
    )
    parameters = "\n".join(
        "    vamp:parameter_binding [ vamp:parameter [ "
        f'vamp:identifier "{name}" ] ; vamp:value "{value}"^^xsd:float ] ;'
        for name, value in bindings
    )
    return (
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
        "@prefix vamp: <http://purl.org/ontology/vamp/> .\n"
        "@prefix : <#> .\n"
        ':transform_plugin a vamp:Plugin ; vamp:identifier "chordino" .\n'
        f':transform_library a vamp:PluginLibrary ; vamp:identifier "{library}" ; '
        "vamp:available_plugin :transform_plugin .\n"
        ":transform a vamp:Transform ;\n"
        "    vamp:plugin :transform_plugin ;\n"
        '    vamp:step_size "2048"^^xsd:int ;\n'
        '    vamp:block_size "16384"^^xsd:int ;\n'
        f"{version_line}"
        f"{parameters}\n"
        '    vamp:output [ vamp:identifier "simplechord" ] .\n'
    )


def _choose(available: Sequence[SonicPlugin], plugin: str, output: str) -> SonicPlugin | None:
    matches = [item for item in available if item.plugin == plugin and item.output == output]
    if not matches:
        return None
    matches.sort(key=lambda item: (item.library != "qm-vamp-plugins", item.library))
    return matches[0]


def _row(feature: CsvFeature) -> dict[str, object]:
    return {
        "timestamp": _timestamp(feature.time_seconds),
        "label": feature.label,
        "featureValues": list(feature.values),
    }


def _plugin(
    role: str,
    display_name: str,
    plugin: SonicPlugin,
    *,
    version: str,
    bpb: int = 4,
) -> BackendPlugin:
    return BackendPlugin(
        role=role,
        display_name=display_name,
        key=plugin.transform,
        version=version,
        parameters={"bpb": float(bpb)} if role == BEAT_PLUGIN else {},
        block_size=0,
        step_size=0,
    )


def _tail(text: str, limit: int = STDERR_TAIL_BYTES) -> str:
    cleaned = " ".join(text.split())
    return cleaned[-limit:] if len(cleaned) > limit else cleaned


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
