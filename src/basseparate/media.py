"""Media boundary: ffprobe metadata, ffmpeg decode, PCM files and import.

Everything here is intentionally free of FastAPI and of the analysis environment
(no torch, no demucs). The only external tools are the system ``ffprobe`` and
``ffmpeg``. Pure mapping helpers (``parse_ffprobe``, ``validate_frame_range``)
are separated from the subprocess calls so they can be tested without I/O.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from basseparate.peaks import PEAK_BUCKET_SIZES, compute_peaks_from_file, encode_peaks

# A decoded block is read and fed to the peak accumulator in chunks. 1 Mi
# frames of stereo float32 is 8 MiB, small enough for any practice machine.
PEAK_CHUNK_FRAMES = 1 << 20
SHA256_CHUNK_BYTES = 1 << 20
DECODE_TIMEOUT_SECONDS = 3600


class MediaError(Exception):
    """A media operation failed; the message is safe to show to the user."""


class MediaCancelled(MediaError):
    """The caller asked to stop; the partial result has been removed."""


class RangeError(MediaError):
    """The requested frame range is outside the asset; maps to HTTP 416."""


@dataclass(frozen=True)
class MediaInfo:
    sample_rate: int
    channels: int
    duration_seconds: float
    codec: str
    bit_rate: int | None
    source_format: str


def _as_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise MediaError(f"ffprobe {label} is not a JSON object")
    return value


def _parse_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise MediaError(f"invalid {label}: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip(), 10)
        except ValueError as error:
            raise MediaError(f"invalid {label}: {value!r}") from error
    raise MediaError(f"invalid {label}: {value!r}")


def _parse_float(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise MediaError(f"invalid {label}: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError as error:
            raise MediaError(f"invalid {label}: {value!r}") from error
    raise MediaError(f"invalid {label}: {value!r}")


def parse_ffprobe(payload: object) -> MediaInfo:
    """Map ffprobe's JSON to the fields the studio needs, or fail clearly."""
    data = _as_mapping(payload, "payload")
    streams = data.get("streams")
    if not isinstance(streams, list):
        raise MediaError("ffprobe payload has no stream list")
    audio: Mapping[str, object] | None = None
    for stream in streams:
        if isinstance(stream, Mapping) and stream.get("codec_type") == "audio":
            audio = stream
            break
    if audio is None:
        raise MediaError("the file contains no audio stream")

    sample_rate = _parse_int(audio.get("sample_rate"), "sample rate")
    if sample_rate <= 0:
        raise MediaError(f"invalid sample rate: {audio.get('sample_rate')!r}")
    channels = _parse_int(audio.get("channels"), "channel count")
    if channels <= 0:
        raise MediaError(f"invalid channel count: {audio.get('channels')!r}")

    container = data.get("format")
    container = container if isinstance(container, Mapping) else {}
    duration_value = audio.get("duration") or container.get("duration")
    if duration_value is None:
        raise MediaError("the file has no audio duration")
    duration = _parse_float(duration_value, "duration")
    if duration < 0:
        raise MediaError(f"invalid duration: {duration_value!r}")

    bit_rate_value = audio.get("bit_rate") or container.get("bit_rate")
    bit_rate: int | None
    try:
        bit_rate = _parse_int(bit_rate_value, "bit rate") if bit_rate_value is not None else None
    except MediaError:
        bit_rate = None

    codec = audio.get("codec_name")
    source_format = container.get("format_name")
    return MediaInfo(
        sample_rate=sample_rate,
        channels=channels,
        duration_seconds=duration,
        codec=codec if isinstance(codec, str) and codec else "unknown",
        bit_rate=bit_rate,
        source_format=source_format if isinstance(source_format, str) else "unknown",
    )


def probe_media(path: Path, *, ffprobe: str = "ffprobe") -> MediaInfo:
    path = Path(path)
    if not path.is_file():
        raise MediaError(f"source file does not exist: {path}")
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except FileNotFoundError as error:
        raise MediaError(f"{ffprobe} is not installed") from error
    except subprocess.TimeoutExpired as error:
        raise MediaError(f"ffprobe timed out reading {path.name}") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = detail[-1] if detail else f"exit {result.returncode}"
        raise MediaError(f"ffprobe could not read {path.name}: {message}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise MediaError(f"ffprobe returned invalid JSON for {path.name}") from error
    return parse_ffprobe(payload)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(SHA256_CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_channels(source_channels: int) -> int:
    """Keep mono mono; fold every multi-channel source to stereo."""
    if source_channels <= 0:
        raise MediaError("the source has no audio channels")
    return 1 if source_channels == 1 else 2


def validate_frame_range(start: int, end: int | None, total_frames: int) -> tuple[int, int]:
    """Boundary check for a ranged PCM read; returns the inclusive/exclusive pair."""
    if start < 0:
        raise RangeError(f"start frame must not be negative, got {start}")
    if end is None:
        end = total_frames
    if end < 0:
        raise RangeError(f"end frame must not be negative, got {end}")
    if start > total_frames:
        raise RangeError(
            f"requested start frame {start} is outside the asset range 0..{total_frames}"
        )
    if end > total_frames:
        raise RangeError(f"requested end frame {end} is outside the asset range 0..{total_frames}")
    if end < start:
        raise RangeError(f"end frame {end} is before start frame {start}")
    return start, end


def interleaved_pcm_bytes(frames: int, channels: int) -> int:
    return frames * channels * 4


def read_pcm_range(
    path: Path,
    *,
    channels: int,
    start: int,
    end: int,
    total_frames: int,
) -> bytes:
    frame_size = channels * 4
    start, end = validate_frame_range(start, end, total_frames)
    expected = interleaved_pcm_bytes(end - start, channels)
    with Path(path).open("rb") as handle:
        handle.seek(start * frame_size)
        payload = handle.read(expected)
    if len(payload) != expected:
        raise MediaError(
            f"PCM file is truncated: expected {expected} bytes at frame {start}, got {len(payload)}"
        )
    return payload


def decode_to_pcm(
    source: Path,
    target: Path,
    *,
    sample_rate: int,
    channels: int,
    duration_seconds: float,
    progress: Callable[[float, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    ffmpeg: str = "ffmpeg",
    timeout_seconds: int = DECODE_TIMEOUT_SECONDS,
) -> int:
    """Decode the first audio stream to interleaved little-endian float32.

    Returns the decoded frame count. Cancellation kills ffmpeg and removes the
    partial output before raising :class:`MediaCancelled`.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    log_path = target.with_name(f"{target.name}.ffmpeg.log")
    command = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-progress",
        "pipe:1",
        "-nostats",
        "-y",
        str(target),
    ]
    if progress is not None:
        progress(0.0, "decoding audio")

    def cancelled() -> bool:
        return is_cancelled is not None and is_cancelled()

    process: subprocess.Popen[bytes] | None = None
    try:
        with log_path.open("wb") as log_handle:
            process = subprocess.Popen(  # noqa: S603 - explicit argv, no shell
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=log_handle,
            )
            if process.stdout is None:  # pragma: no cover - defensive
                raise MediaError("ffmpeg stdout was not captured")
            for raw in process.stdout:
                if cancelled():
                    raise MediaCancelled("audio decode was cancelled")
                line = raw.decode("utf-8", "replace").strip()
                if progress is not None and line.startswith(("out_time_us=", "out_time_ms=")):
                    _, _, raw_value = line.partition("=")
                    try:
                        microseconds = int(raw_value)
                    except ValueError:
                        continue
                    if duration_seconds > 0 and microseconds >= 0:
                        fraction = min(1.0, microseconds / 1_000_000.0 / duration_seconds)
                        progress(fraction, "decoding audio")
            returncode = process.wait(timeout=timeout_seconds)
    except FileNotFoundError as error:
        raise MediaError(f"{ffmpeg} is not installed") from error
    except subprocess.TimeoutExpired as error:
        raise MediaError(f"ffmpeg timed out decoding {source.name}") from error
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        if cancelled() and target.exists():
            target.unlink(missing_ok=True)

    if returncode != 0:
        detail: list[str] = []
        if log_path.is_file():
            detail = log_path.read_text("utf-8", "replace").strip().splitlines()
        target.unlink(missing_ok=True)
        message = detail[-1] if detail else f"ffmpeg exited with {returncode}"
        raise MediaError(f"ffmpeg could not decode {source.name}: {message}")
    log_path.unlink(missing_ok=True)
    size = target.stat().st_size
    frame_size = channels * 4
    if size == 0:
        target.unlink(missing_ok=True)
        raise MediaError(f"ffmpeg decoded no audio from {source.name}")
    if size % frame_size:
        target.unlink(missing_ok=True)
        raise MediaError(f"decoded PCM for {source.name} is not frame-aligned")
    return size // frame_size


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Replace ``path`` atomically: a crash leaves the previous file intact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class DecodedAsset:
    asset_id: str
    directory: Path
    source_name: str
    source_format: str
    codec: str
    sample_rate: int
    channels: int
    frames: int
    content_sha256: str
    peak_counts: Mapping[int, int]

    @property
    def duration_seconds(self) -> float:
        return self.frames / self.sample_rate


def _safe_suffix(source: Path) -> str:
    suffix = source.suffix.lower()
    if suffix and suffix[1:].isalnum():
        return suffix
    return ".bin"


def _check_cancelled(is_cancelled: Callable[[], bool] | None) -> None:
    if is_cancelled is not None and is_cancelled():
        raise MediaCancelled("import was cancelled")


def import_media(
    source: Path,
    *,
    assets_root: Path,
    sample_rate: int | None = None,
    progress: Callable[[float, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> DecodedAsset:
    """Probe, hash, copy, decode and derive peaks for one source file.

    The asset id is content addressed plus the decode target, so re-importing
    the same bytes at the same rate and channel layout is deterministic.
    """

    def report(fraction: float, message: str) -> None:
        if progress is not None:
            progress(fraction, message)

    source = Path(source)
    if not source.is_file():
        raise MediaError(f"source file does not exist: {source}")
    _check_cancelled(is_cancelled)
    report(0.02, "reading metadata")
    info = probe_media(source, ffprobe=ffprobe)
    _check_cancelled(is_cancelled)
    report(0.08, "hashing source")
    digest = file_sha256(source)

    target_rate = sample_rate if sample_rate is not None else info.sample_rate
    if target_rate <= 0:
        raise MediaError(f"invalid project sample rate: {target_rate}")
    channels = canonical_channels(info.channels)
    asset_id = f"{digest[:16]}-{target_rate}-{channels}"
    directory = Path(assets_root) / asset_id
    created = not directory.exists()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        _check_cancelled(is_cancelled)
        report(0.15, "copying source")
        source_target = directory / f"source{_safe_suffix(source)}"
        if not source_target.is_file() or source_target.stat().st_size != source.stat().st_size:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".source.", suffix=".tmp", dir=directory
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    with source.open("rb") as reader:
                        shutil.copyfileobj(reader, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary.replace(source_target)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise

        pcm_path = directory / "pcm.f32"
        _check_cancelled(is_cancelled)
        report(0.2, "decoding audio")
        decoded_frames = decode_to_pcm(
            source,
            pcm_path,
            sample_rate=target_rate,
            channels=channels,
            duration_seconds=info.duration_seconds,
            progress=lambda fraction, message: report(0.2 + 0.6 * fraction, message),
            is_cancelled=is_cancelled,
            ffmpeg=ffmpeg,
        )
        _check_cancelled(is_cancelled)

        peak_counts: dict[int, int] = {}
        for index, bucket_size in enumerate(PEAK_BUCKET_SIZES):
            _check_cancelled(is_cancelled)
            report(0.8 + 0.2 * index / len(PEAK_BUCKET_SIZES), f"peaks {bucket_size}")
            peaks = compute_peaks_from_file(
                pcm_path,
                channels=channels,
                frames=decoded_frames,
                bucket_size=bucket_size,
                chunk_frames=PEAK_CHUNK_FRAMES,
            )
            atomic_write_bytes(
                directory / f"peaks-{bucket_size}.bin",
                encode_peaks(peaks, sample_rate=target_rate),
            )
            peak_counts[bucket_size] = peaks.bucket_count

        report(0.99, "writing asset manifest")
        manifest = {
            "schema_version": 1,
            "asset_id": asset_id,
            "source_name": source.name,
            "source_format": info.source_format,
            "codec": info.codec,
            "sample_rate": target_rate,
            "source_sample_rate": info.sample_rate,
            "channels": channels,
            "source_channels": info.channels,
            "frames": decoded_frames,
            "duration_seconds": decoded_frames / target_rate,
            "content_sha256": digest,
            "peak_counts": {str(bucket): count for bucket, count in peak_counts.items()},
        }
        atomic_write_bytes(
            directory / "asset.json",
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
        )
    except BaseException:
        if created:
            shutil.rmtree(directory, ignore_errors=True)
        raise

    report(1.0, "imported")
    return DecodedAsset(
        asset_id=asset_id,
        directory=directory,
        source_name=source.name,
        source_format=info.source_format,
        codec=info.codec,
        sample_rate=target_rate,
        channels=channels,
        frames=decoded_frames,
        content_sha256=digest,
        peak_counts=peak_counts,
    )
