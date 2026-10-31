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
    """The requested range is outside the asset; maps to HTTP 416."""


@dataclass(frozen=True)
class ByteRange:
    """One inclusive HTTP byte range over a complete byte stream."""

    start: int
    end: int
    total: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    @property
    def content_range(self) -> str:
        return f"bytes {self.start}-{self.end}/{self.total}"


@dataclass(frozen=True)
class PcmSlice:
    """A frame-aligned PCM read, from either a Range header or query params."""

    payload: bytes
    status_code: int
    start_frame: int
    end_frame: int
    total_frames: int
    content_range: str | None
    byte_start: int
    byte_end: int


def parse_http_range(range_header: str | None, total_bytes: int) -> ByteRange | None:
    """Parse a single ``bytes=`` range; other units are ignored (RFC 9110).

    Unsatisfiable, malformed and multiple ranges raise :class:`RangeError` so
    the route can return 416 with the required ``Content-Range: bytes */N``.
    """
    if range_header is None:
        return None
    value = range_header.strip()
    if not value:
        return None
    unit, separator, spec = value.partition("=")
    if unit.strip().lower() != "bytes":
        return None
    if not separator:
        raise RangeError(f"invalid Range header: {range_header!r}")
    spec = spec.strip()
    if not spec:
        raise RangeError("the Range header is empty")
    if "," in spec:
        raise RangeError("multiple byte ranges are not supported; request one range")
    first, dash, last = spec.partition("-")
    if not dash:
        raise RangeError(f"invalid Range header: {range_header!r}")
    try:
        if first == "":
            suffix = int(last, 10)
            if suffix <= 0:
                raise RangeError(f"range {spec!r} is outside the asset ({total_bytes} bytes)")
            if total_bytes <= 0:
                raise RangeError(f"range {spec!r} is outside the asset (0 bytes)")
            start = max(0, total_bytes - suffix)
            end = total_bytes - 1
        else:
            start = int(first, 10)
            end = total_bytes - 1 if last == "" else int(last, 10)
    except ValueError as error:
        raise RangeError(f"invalid Range header: {range_header!r}") from error
    if total_bytes <= 0:
        raise RangeError(f"range {spec!r} is outside the asset (0 bytes)")
    if start < 0 or end < start:
        raise RangeError(f"range {spec!r} ends before it starts")
    if start >= total_bytes:
        raise RangeError(f"range {spec!r} is outside the asset ({total_bytes} bytes)")
    end = min(end, total_bytes - 1)
    return ByteRange(start=start, end=end, total=total_bytes)


def _read_byte_range(path: Path, byte_range: ByteRange) -> bytes:
    with Path(path).open("rb") as handle:
        handle.seek(byte_range.start)
        payload = handle.read(byte_range.length)
    if len(payload) != byte_range.length:
        raise MediaError(
            f"PCM file is truncated: expected {byte_range.length} bytes at "
            f"{byte_range.start}, got {len(payload)}"
        )
    return payload


def read_pcm_slice(
    path: Path,
    *,
    channels: int,
    total_frames: int,
    range_header: str | None,
    start: int = 0,
    end: int | None = None,
) -> PcmSlice:
    """Read PCM bytes for an HTTP Range header or the legacy start/end query.

    Range requests must be aligned to whole f32le frames; the returned
    ``content_range`` uses byte positions, while the frame headers describe the
    same slice in project frames.
    """
    path = Path(path)
    if channels <= 0:
        raise MediaError("the PCM channel count must be positive")
    if total_frames < 0:
        raise MediaError("the PCM frame count must not be negative")
    frame_size = channels * 4
    expected_bytes = total_frames * frame_size
    try:
        actual_bytes = path.stat().st_size
    except OSError as error:
        raise MediaError(f"cannot read PCM file {path}: {error}") from error
    if actual_bytes != expected_bytes:
        raise MediaError(
            f"PCM file size {actual_bytes} does not match {total_frames} frames "
            f"at {channels} channels ({expected_bytes} bytes)"
        )
    byte_range = parse_http_range(range_header, actual_bytes)
    if byte_range is not None:
        if byte_range.start % frame_size or (byte_range.end + 1) % frame_size:
            raise RangeError(f"Range {range_header!r} is not aligned to {frame_size}-byte frames")
        start_frame = byte_range.start // frame_size
        end_frame = (byte_range.end + 1) // frame_size
        return PcmSlice(
            payload=_read_byte_range(path, byte_range),
            status_code=206,
            start_frame=start_frame,
            end_frame=end_frame,
            total_frames=total_frames,
            content_range=byte_range.content_range,
            byte_start=byte_range.start,
            byte_end=byte_range.end,
        )
    start_frame, end_frame = validate_frame_range(start, end, total_frames)
    return PcmSlice(
        payload=read_pcm_range(
            path,
            channels=channels,
            start=start_frame,
            end=end_frame,
            total_frames=total_frames,
        ),
        status_code=200,
        start_frame=start_frame,
        end_frame=end_frame,
        total_frames=total_frames,
        content_range=None,
        byte_start=start_frame * frame_size,
        byte_end=end_frame * frame_size - 1,
    )


def pcm_response_headers(
    *,
    start_frame: int,
    end_frame: int,
    total_frames: int,
    sample_rate: int,
    channels: int,
    content_range: str | None = None,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    headers = {
        "accept-ranges": "bytes",
        "x-frame-start": str(start_frame),
        "x-frame-end": str(end_frame),
        "x-frame-count": str(end_frame - start_frame),
        "x-sample-rate": str(sample_rate),
        "x-channels": str(channels),
        "x-total-frames": str(total_frames),
        "cache-control": "private, max-age=3600",
    }
    if content_range is not None:
        headers["content-range"] = content_range
    if extra:
        headers.update(extra)
    return headers


def unsatisfiable_range_headers(total_bytes: int) -> dict[str, str]:
    return {"accept-ranges": "bytes", "content-range": f"bytes */{total_bytes}"}


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

    if cancelled():
        raise MediaCancelled("audio decode was cancelled")
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
