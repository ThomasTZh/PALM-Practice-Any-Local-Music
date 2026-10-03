"""ffprobe media inspection (M1.3).

Runs ``ffprobe`` as a subprocess against a completed local upload and
reduces the JSON output to the validated ``ProbeResult`` domain model.

Security properties:
- The input path is always a server-generated local file; ffprobe is
  invoked with an argument array (no shell) and stdin disabled, so there
  is no interaction and no way to reach the network.
- The subprocess runs under a hard timeout and its stdout/stderr are
  read under a byte bound.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from basseparate.domain.import_record import AudioStreamInfo, ProbeResult
from basseparate.media._process import (
    SubprocessOutputError,
    read_stream_bounded,
)
from basseparate.media._process import (
    kill as _kill,
)
from basseparate.media._process import (
    terminate_gracefully as _terminate_gracefully,
)
from basseparate.media._process import (
    wait_for_cancel as _wait_for_cancel,
)

DEFAULT_PROBE_TIMEOUT_SECONDS = 30.0
MAX_PROBE_OUTPUT_BYTES = 10 * 1024 * 1024  # 10 MiB per stream
_VERSION_TIMEOUT_SECONDS = 10.0

# Application limits (not claims about FFmpeg's capabilities).
MIN_SAMPLE_RATE = 8_000
MAX_SAMPLE_RATE = 192_000
MIN_CHANNELS = 1
MAX_CHANNELS = 8

_VERSION_LINE_RE = re.compile(r"^\S+ version (\S+)")

# FFmpeg 7+ dropped the channel_layout field for many containers; derive
# the conventional name for the channel counts we support.
_LAYOUT_BY_CHANNELS = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}


class ProbeError(Exception):
    """Base class for probe failures."""


class ProbeTimeoutError(ProbeError):
    """ffprobe did not finish within the allowed time."""


class ProbeFailedError(ProbeError):
    """ffprobe could not run or produced unusable output."""


class NoAudioStreamError(ProbeError):
    """The container holds no audio streams."""


class UnsupportedMediaError(ProbeError):
    """The media is outside the supported sample-rate/channel envelope."""


class ProbeCancelledError(ProbeError):
    """The probe was cancelled before it completed."""


async def _read_bounded(stream: asyncio.StreamReader, limit: int) -> bytes:
    """Read a subprocess stream, refusing output beyond ``limit`` bytes."""
    try:
        return await read_stream_bounded(stream, limit, "ffprobe output")
    except SubprocessOutputError as exc:
        raise ProbeFailedError(str(exc)) from exc


async def _tool_version(name: str) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            name,
            "-version",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        raise ProbeFailedError(f"could not launch {name}: {exc}") from exc
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_VERSION_TIMEOUT_SECONDS)
    except TimeoutError:
        _kill(proc)
        raise ProbeFailedError(f"{name} -version timed out") from None
    if proc.returncode != 0:
        raise ProbeFailedError(f"{name} -version exited with {proc.returncode}")
    first_line = stdout.decode("utf-8", errors="replace").splitlines()[0] if stdout else ""
    match = _VERSION_LINE_RE.match(first_line)
    if match is None:
        raise ProbeFailedError(f"unrecognized {name} version output: {first_line!r}")
    return match.group(1)


_VERSION_CACHE: tuple[str, str] | None = None


async def tool_versions() -> tuple[str, str]:
    """Return ``(ffmpeg_version, ffprobe_version)``, cached per process."""
    global _VERSION_CACHE
    if _VERSION_CACHE is None:
        ffmpeg, ffprobe = await asyncio.gather(_tool_version("ffmpeg"), _tool_version("ffprobe"))
        _VERSION_CACHE = (ffmpeg, ffprobe)
    return _VERSION_CACHE


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise UnsupportedMediaError(f"missing or invalid {field}")
    try:
        result = int(value)
    except ValueError as exc:
        raise UnsupportedMediaError(f"invalid {field}: {value!r}") from exc
    if result < 0:
        raise UnsupportedMediaError(f"{field} must be nonnegative, got {result}")
    return result


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if result >= 0 else None


def _as_tag(tags: Any, key: str) -> str | None:
    if not isinstance(tags, dict):
        return None
    value = tags.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _parse_audio_stream(stream: dict[str, Any]) -> AudioStreamInfo:
    index = _as_int(stream.get("index"), "stream index")
    codec = stream.get("codec_name")
    if not isinstance(codec, str) or not codec:
        raise UnsupportedMediaError(f"audio stream {index} has no codec name")
    sample_rate = _as_int(stream.get("sample_rate"), f"stream {index} sample rate")
    channel_count = _as_int(stream.get("channels"), f"stream {index} channel count")
    layout = stream.get("channel_layout")
    if not isinstance(layout, str) or not layout:
        layout = _LAYOUT_BY_CHANNELS.get(channel_count)
    disposition = stream.get("disposition")
    is_default = isinstance(disposition, dict) and bool(disposition.get("default", 0))
    tags = stream.get("tags")
    return AudioStreamInfo(
        index=index,
        codec=codec,
        sample_rate=sample_rate,
        channel_count=channel_count,
        channel_layout=layout,
        language=_as_tag(tags, "language"),
        title=_as_tag(tags, "title"),
        is_default=is_default,
        estimated_duration_seconds=_as_float(stream.get("duration")),
        start_timestamp_seconds=_as_float(stream.get("start_time")),
    )


def parse_probe_data(
    data: dict[str, Any],
    file_size: int,
    ffmpeg_version: str,
    ffprobe_version: str,
) -> ProbeResult:
    """Validate parsed ffprobe JSON and reduce it to a ProbeResult.

    ``file_size`` is the on-disk size of the probed file; it is used as a
    fallback when the container does not report its own size.
    """
    format_info = data.get("format")
    if not isinstance(format_info, dict):
        raise ProbeFailedError("ffprobe output is missing the format section")
    format_name = format_info.get("format_name")
    if not isinstance(format_name, str) or not format_name:
        raise ProbeFailedError("ffprobe output is missing format_name")

    tags = format_info.get("tags")
    size_raw = format_info.get("size")
    byte_count = file_size
    if isinstance(size_raw, (int, str)) and not isinstance(size_raw, bool):
        try:
            parsed_size = int(size_raw)
        except ValueError:
            parsed_size = -1
        if parsed_size >= 0:
            byte_count = parsed_size

    streams = data.get("streams")
    audio_streams: list[AudioStreamInfo] = []
    if isinstance(streams, list):
        for stream in streams:
            if not isinstance(stream, dict) or stream.get("codec_type") != "audio":
                continue
            audio_streams.append(_parse_audio_stream(stream))

    if not audio_streams:
        raise NoAudioStreamError(f"the file contains no audio streams (format: {format_name})")

    for stream in audio_streams:
        if not MIN_SAMPLE_RATE <= stream.sample_rate <= MAX_SAMPLE_RATE:
            raise UnsupportedMediaError(
                f"audio stream {stream.index} sample rate {stream.sample_rate} Hz is outside "
                f"the supported range {MIN_SAMPLE_RATE}–{MAX_SAMPLE_RATE} Hz"
            )
        if not MIN_CHANNELS <= stream.channel_count <= MAX_CHANNELS:
            raise UnsupportedMediaError(
                f"audio stream {stream.index} has {stream.channel_count} channels; "
                f"the supported range is {MIN_CHANNELS}–{MAX_CHANNELS}"
            )

    try:
        return ProbeResult(
            format_name=format_name,
            estimated_duration_seconds=_as_float(format_info.get("duration")),
            byte_count=byte_count,
            title=_as_tag(tags, "title"),
            artist=_as_tag(tags, "artist"),
            ffmpeg_version=ffmpeg_version,
            ffprobe_version=ffprobe_version,
            audio_streams=tuple(audio_streams),
        )
    except ValueError as exc:
        raise UnsupportedMediaError(f"ffprobe stream data is not usable: {exc}") from exc


async def probe_media(
    path: Path,
    timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
    cancel_event: threading.Event | None = None,
) -> ProbeResult:
    """Probe a local media file and return its validated metadata.

    Raises ``ProbeTimeoutError``, ``ProbeFailedError``,
    ``NoAudioStreamError``, ``UnsupportedMediaError``, or
    ``ProbeCancelledError`` (when ``cancel_event`` is set).
    """
    if cancel_event is not None and cancel_event.is_set():
        raise ProbeCancelledError("probe was cancelled before it started")
    if not path.is_file():
        raise ProbeFailedError(f"media file not found: {path.name}")

    args: Sequence[str] = (
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-show_error",
        str(path),
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise ProbeFailedError(f"could not launch ffprobe: {exc}") from exc

    stdout_stream = proc.stdout
    stderr_stream = proc.stderr
    if stdout_stream is None or stderr_stream is None:
        _kill(proc)
        raise ProbeFailedError("ffprobe subprocess streams are unavailable")

    read_output: list[bytes] = []

    async def _read_all() -> None:
        read_output[:] = list(
            await asyncio.gather(
                _read_bounded(stdout_stream, MAX_PROBE_OUTPUT_BYTES),
                _read_bounded(stderr_stream, MAX_PROBE_OUTPUT_BYTES),
            )
        )

    cancel_task: asyncio.Task[None] | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            read_task = asyncio.ensure_future(_read_all())
            if cancel_event is not None:
                cancel_task = asyncio.ensure_future(_wait_for_cancel(cancel_event))
            waitables: set[asyncio.Task[None]] = {read_task}
            if cancel_task is not None:
                waitables.add(cancel_task)
            done, _pending = await asyncio.wait(
                waitables,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_task is not None and cancel_task in done:
                read_task.cancel()
                with contextlib.suppress(BaseException):
                    await read_task
                await _terminate_gracefully(proc)
                raise ProbeCancelledError("probe was cancelled")
            if cancel_task is not None:
                cancel_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await cancel_task
            read_task.result()
            stdout, stderr = read_output[0], read_output[1]
            returncode = await proc.wait()
    except TimeoutError as exc:
        await _terminate_gracefully(proc)
        raise ProbeTimeoutError(
            f"ffprobe did not finish within {timeout_seconds:g} seconds"
        ) from exc
    except ProbeFailedError:
        await _terminate_gracefully(proc)
        raise

    if returncode != 0:
        detail = _error_detail(stdout) or stderr.decode("utf-8", errors="replace")[:500]
        raise ProbeFailedError(f"ffprobe exited with {returncode}: {detail}".strip())

    try:
        data = json.loads(stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise ProbeFailedError(f"ffprobe returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProbeFailedError("ffprobe JSON output is not an object")

    file_size = path.stat().st_size
    ffmpeg_version, ffprobe_version = await tool_versions()
    return parse_probe_data(data, file_size, ffmpeg_version, ffprobe_version)


def _error_detail(stdout: bytes) -> str:
    """Extract the ``error`` section ffprobe emits with -show_error."""
    try:
        data = json.loads(stdout.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message[:500]
    return ""
