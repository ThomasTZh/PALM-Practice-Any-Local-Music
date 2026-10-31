"""Mixdown export: stem PCM layers -> one WAV at the project rate.

The mixer is intentionally small and explicit: a layer is a decoded PCM file
plus a linear gain and mute/solo state. Stem metadata comes from the project
document, so an export can be reproduced after a restart from the project JSON
alone. Writes are atomic (temp file in the destination directory, fsync,
replace), and the output length is always ``project.audio.frames``.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import tempfile
import wave
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from basseparate.projects import Project

BYTES_PER_SAMPLE = 2
CHUNK_FRAMES = 1 << 20
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class ExportError(RuntimeError):
    """The mixdown cannot be produced; the message is safe for the UI."""


@dataclass(frozen=True)
class ChannelMix:
    gain: float = 1.0
    muted: bool = False
    solo: bool = False
    pan: float = 0.0


@dataclass(frozen=True)
class MixerSpec:
    channels: Mapping[str, ChannelMix] = field(default_factory=dict)
    master_gain: float = 1.0


@dataclass(frozen=True)
class MixLayer:
    id: str
    pcm_path: Path
    channels: int
    gain: float = 1.0
    offset_frames: int = 0


@dataclass(frozen=True)
class MixdownResult:
    path: Path
    frames: int
    sample_rate: int
    channels: int
    bytes: int
    sha256: str
    layer_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "frames": self.frames,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "layers": list(self.layer_ids),
        }


def _as_float(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    number = float(value)
    return number if math.isfinite(number) else default


def _as_bool(value: object, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _channel_mix(
    stem: Mapping[str, Any],
    document_mixer: Mapping[str, Any],
    spec: MixerSpec | None,
    stem_id: str,
) -> ChannelMix:
    base = ChannelMix(
        gain=max(0.0, _as_float(stem.get("gain", 1.0), 1.0)),
        muted=_as_bool(stem.get("muted", stem.get("mute", False))),
        solo=_as_bool(stem.get("solo", False)),
    )
    document_channel = document_mixer.get(stem_id)
    if isinstance(document_channel, Mapping):
        base = ChannelMix(
            gain=max(0.0, _as_float(document_channel.get("gain", base.gain), base.gain)),
            muted=_as_bool(document_channel.get("muted", document_channel.get("mute", base.muted)), base.muted),
            solo=_as_bool(document_channel.get("solo", base.solo), base.solo),
        )
    elif isinstance(document_channel, (int, float)) and not isinstance(document_channel, bool):
        base = ChannelMix(gain=max(0.0, float(document_channel)), muted=base.muted, solo=base.solo)
    if spec is not None:
        override = spec.channels.get(stem_id) or spec.channels.get(str(stem.get("name", stem_id)))
        if override is not None:
            base = ChannelMix(gain=max(0.0, override.gain), muted=override.muted, solo=override.solo)
    return base


def _stem_asset_id(stem: Mapping[str, Any], assets_root: Path, stem_id: str) -> str | None:
    for key in ("asset_id", "assetId", "peaksAssetId", "peaks_asset_id"):
        value = stem.get(key)
        if isinstance(value, str) and value:
            return value
    if (assets_root / stem_id / "pcm.f32").is_file():
        return stem_id
    return None


def _stem_pcm_path(
    stem: Mapping[str, Any], assets_root: Path, stem_id: str
) -> tuple[Path, str | None]:
    for key in ("pcm_path", "pcmPath", "path"):
        value = stem.get(key)
        if not isinstance(value, str) or not value:
            continue
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = assets_root / candidate
        try:
            candidate.resolve().relative_to(assets_root.resolve())
        except ValueError as error:
            raise ExportError(f"stem {stem_id} references a PCM outside the asset root") from error
        return candidate, stem_id
    asset_id = _stem_asset_id(stem, assets_root, stem_id)
    if asset_id is None:
        raise ExportError(f"stem {stem_id} has no asset id or PCM path")
    return assets_root / asset_id / "pcm.f32", asset_id


def _layer_channels(stem: Mapping[str, Any], project_channels: int) -> int:
    channels = stem.get("channels", project_channels)
    if isinstance(channels, bool) or not isinstance(channels, int) or channels < 1:
        return project_channels
    return channels


def build_mix_layers(
    project: Project,
    *,
    assets_root: Path,
    mixer: MixerSpec | None = None,
) -> tuple[MixLayer, ...]:
    """Resolve the project's stems (or source asset) into audible PCM layers."""
    assets_root = Path(assets_root)
    document = project.document
    document_mixer = document.get("mixer")
    document_mixer = document_mixer if isinstance(document_mixer, Mapping) else {}
    stems_raw = document.get("stems")
    stems = (
        [stem for stem in stems_raw if isinstance(stem, Mapping)]
        if isinstance(stems_raw, list)
        else []
    )
    mixed: list[tuple[MixLayer, ChannelMix]] = []
    if stems:
        for index, stem in enumerate(stems):
            stem_id = str(stem.get("id") or stem.get("name") or f"stem-{index + 1}")
            pcm_path, _asset_id = _stem_pcm_path(stem, assets_root, stem_id)
            if not pcm_path.is_file():
                raise ExportError(f"stem {stem_id} has no PCM at {pcm_path}")
            channel = _channel_mix(stem, document_mixer, mixer, stem_id)
            offset = stem.get("offset_frames", stem.get("offsetFrame", 0))
            offset_frames = int(offset) if isinstance(offset, (int, float)) and not isinstance(offset, bool) else 0
            mixed.append(
                (
                    MixLayer(
                        id=stem_id,
                        pcm_path=pcm_path,
                        channels=_layer_channels(stem, project.audio.channels),
                        gain=channel.gain,
                        offset_frames=max(0, offset_frames),
                    ),
                    channel,
                )
            )
        any_solo = any(channel.solo for _layer, channel in mixed)
        audible = [
            layer
            for layer, channel in mixed
            if not channel.muted and (not any_solo or channel.solo) and channel.gain > 0
        ]
        if not audible:
            raise ExportError("the project has no audible stems to export")
        return tuple(audible)

    source_id = "source"
    pcm_path = assets_root / project.audio.asset_id / "pcm.f32"
    if not pcm_path.is_file():
        raise ExportError(
            f"project {project.id} has no decoded PCM at assets/{project.audio.asset_id}/pcm.f32"
        )
    channel = _channel_mix({"gain": 1.0}, document_mixer, mixer, source_id)
    if channel.muted or channel.gain <= 0:
        raise ExportError("the project source is muted; there is nothing to export")
    master = mixer.master_gain if mixer is not None else _as_float(
        document_mixer.get("master_gain", 1.0), 1.0
    )
    if master <= 0:
        raise ExportError("the master gain is zero; there is nothing to export")
    return (
        MixLayer(
            id=source_id,
            pcm_path=pcm_path,
            channels=project.audio.channels,
            gain=channel.gain,
        ),
    )


def _master_gain(project: Project, mixer: MixerSpec | None) -> float:
    if mixer is not None:
        value = mixer.master_gain
    else:
        raw = project.document.get("mixer")
        value = _as_float(raw.get("master_gain", 1.0), 1.0) if isinstance(raw, Mapping) else 1.0
    if not math.isfinite(value) or value < 0:
        raise ExportError(f"invalid master gain {value!r}")
    return value


def _layer_total_frames(layer: MixLayer) -> int:
    frame_bytes = layer.channels * 4
    try:
        size = layer.pcm_path.stat().st_size
    except OSError as error:
        raise ExportError(f"cannot read stem PCM {layer.pcm_path}: {error}") from error
    return size // frame_bytes


def _read_layer_chunk(
    layer: MixLayer,
    *,
    start: int,
    count: int,
    output_channels: int,
) -> NDArray[np.float32]:
    out = np.zeros((count, output_channels), dtype=np.float32)
    total = _layer_total_frames(layer)
    project_lo = max(start, layer.offset_frames)
    project_hi = min(start + count, layer.offset_frames + total)
    if project_hi <= project_lo:
        return out
    read_count = project_hi - project_lo
    source_start = project_lo - layer.offset_frames
    with layer.pcm_path.open("rb") as handle:
        handle.seek(source_start * layer.channels * 4)
        raw = handle.read(read_count * layer.channels * 4)
    if len(raw) != read_count * layer.channels * 4:
        raise ExportError(
            f"stem {layer.id} is truncated at frame {source_start}: "
            f"expected {read_count} frames"
        )
    data = np.frombuffer(raw, dtype="<f4").reshape(read_count, layer.channels)
    destination = slice(project_lo - start, project_hi - start)
    if layer.channels == output_channels:
        out[destination] = data
    elif layer.channels == 1:
        out[destination] = data[:, 0:1]
    elif layer.channels > output_channels:
        out[destination] = data[:, :output_channels]
    else:
        out[destination, : layer.channels] = data
    return out


def _safe_name(project: Project) -> str:
    cleaned = SAFE_NAME.sub("-", project.name).strip("-.")
    return (cleaned or "mixdown")[:80]


def export_filename(project: Project) -> str:
    return f"{_safe_name(project)}.wav"


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def export_mixdown(
    project: Project,
    *,
    assets_root: Path,
    destination: Path,
    mixer: MixerSpec | None = None,
    chunk_frames: int = CHUNK_FRAMES,
) -> MixdownResult:
    """Render one 16-bit PCM WAV with exactly ``project.audio.frames`` frames."""
    if chunk_frames <= 0:
        raise ValueError("chunk_frames must be positive")
    sample_rate = project.audio.sample_rate
    channels = project.audio.channels
    frames = project.audio.frames
    if sample_rate <= 0 or channels <= 0 or frames < 0:
        raise ExportError("the project has invalid audio metadata")
    layers = build_mix_layers(project, assets_root=assets_root, mixer=mixer)
    master = _master_gain(project, mixer)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    written = 0
    try:
        with os.fdopen(descriptor, "wb") as handle:
            with wave.open(handle, "wb") as wav:
                wav.setnchannels(channels)
                wav.setsampwidth(BYTES_PER_SAMPLE)
                wav.setframerate(sample_rate)
                wav.setnframes(frames)
                for start in range(0, frames, chunk_frames):
                    count = min(chunk_frames, frames - start)
                    mix = np.zeros((count, channels), dtype=np.float32)
                    for layer in layers:
                        mix += layer.gain * _read_layer_chunk(
                            layer, start=start, count=count, output_channels=channels
                        )
                    clip = np.clip(mix.astype(np.float64) * master, -1.0, 1.0)
                    pcm = np.round(clip * 32767.0).astype("<i2")
                    wav.writeframes(pcm.tobytes())
                    written += count
            handle.flush()
            os.fsync(handle.fileno())
        if written != frames:
            raise ExportError(f"mixdown wrote {written} frames, expected {frames}")
        temporary.replace(destination)
        _fsync_directory(destination.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    payload = destination.read_bytes()
    return MixdownResult(
        path=destination,
        frames=frames,
        sample_rate=sample_rate,
        channels=channels,
        bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        layer_ids=tuple(layer.id for layer in layers),
    )


def safe_export_component(value: str) -> str:
    """A filename-safe component for export ids/names."""
    cleaned = SAFE_NAME.sub("-", value).strip("-.")
    return cleaned or "export"


__all__ = [
    "ChannelMix",
    "ExportError",
    "MixdownResult",
    "MixerSpec",
    "MixLayer",
    "build_mix_layers",
    "export_filename",
    "export_mixdown",
    "safe_export_component",
]
