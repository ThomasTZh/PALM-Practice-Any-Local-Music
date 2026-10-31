"""Piper JSON-lines client for the preserved local Vamp plugins.

The studio never loads native Vamp code in-process and never downloads a
plugin. It starts the preserved ``piper-vamp-simple-server`` from
``storage/tools/sv`` with ``LD_LIBRARY_PATH`` and ``VAMP_PATH`` pointing at the
offline plugin pack, then speaks the Piper JSON protocol over stdin/stdout.

Plugin lookup is by display name ("Chordino", "Key Detector", "Bar and Beat
Tracker"). The embed keys of the current AppImage extraction are kept only as
a fallback, because those keys change with the library file names.

The server emits Latin-1 bytes in some plugin descriptions, and its feature
and input buffers are large. Two consequences are handled here:

* responses are decoded as Latin-1, not strict UTF-8;
* input blocks are sent as base64 float32 strings, which the JSON protocol
  explicitly accepts and which is around three times faster than number lists.

Cancellation kills the child immediately and the caller never receives a
partial result. Every error carries the tail of the server's stderr so a
missing library, a rejected message or a plugin crash is actionable.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import select
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

import numpy as np
from numpy.typing import NDArray

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# The JSON protocol accepts these adapter names verbatim. AdaptInputDomain is
# required for frequency-domain plugins such as Chordino: without it the
# server expects a pre-computed spectrum and rejects the time-domain block.
ADAPTER_FLAGS = ("AdaptInputDomain",)

# Display names are the primary key. These keys are a fallback for a pack whose
# files were renamed or whose plugin descriptor names are unavailable.
FALLBACK_KEYS: dict[str, tuple[str, ...]] = {
    "Chordino": ("embed-07-8888130:chordino", "nnls-chroma:chordino"),
    "Key Detector": ("embed-12-10378903:qm-keydetector", "qm-vamp-plugins:qm-keydetector"),
    "Bar and Beat Tracker": (
        "embed-12-10378903:qm-barbeattracker",
        "qm-vamp-plugins:qm-barbeattracker",
    ),
}

STDERR_TAIL_LIMIT = 4096


class PiperError(RuntimeError):
    """A Piper/Vamp operation failed; the message is safe to show to the user."""


class PiperUnavailable(PiperError):
    """The configured server, library directory or plugin pack is missing."""


class PiperTimeout(PiperError):
    """The server did not answer a request before its deadline."""


class PiperProcessError(PiperError):
    """The server rejected a request or exited with a non-zero status."""


class AnalysisCancelled(PiperError):
    """The caller asked to stop; the child has been killed and nothing written."""


@dataclass(frozen=True)
class PiperPaths:
    """The three preserved paths a Piper run needs."""

    server: Path
    plugin_path: Path
    library_path: Path

    @classmethod
    def for_project(cls, root: Path | None = None) -> PiperPaths:
        """Resolve the project's preserved assets, honouring explicit overrides."""
        base = (Path(root) if root is not None else PROJECT_ROOT).resolve()
        sv = base / "storage" / "tools" / "sv" / "squashfs-root"
        return cls(
            server=Path(
                os.environ.get(
                    "BASSEPARATE_PIPER", str(sv / "usr" / "bin" / "piper-vamp-simple-server")
                )
            ),
            plugin_path=Path(
                os.environ.get(
                    "BASSEPARATE_VAMP_PLUGINS", str(base / "storage" / "tools" / "plugins")
                )
            ),
            library_path=Path(os.environ.get("BASSEPARATE_PIPER_LIBS", str(sv / "usr" / "lib"))),
        )

    def validate(self) -> None:
        """Fail with an actionable message naming the missing asset."""
        if not self.server.is_file():
            raise PiperUnavailable(
                f"Piper server not found at {self.server}. Restore the preserved offline "
                "asset under storage/tools/sv (or set BASSEPARATE_PIPER); `make bootstrap` "
                "checks the local toolchain and never downloads."
            )
        if not os.access(self.server, os.X_OK):
            raise PiperUnavailable(
                f"Piper server is not executable: {self.server}. Restore the execute bit "
                "on the preserved storage/tools/sv asset."
            )
        if not self.plugin_path.is_dir():
            raise PiperUnavailable(
                f"Vamp plugin pack not found at {self.plugin_path}. Restore the preserved "
                "offline pack under storage/tools/plugins (or set BASSEPARATE_VAMP_PLUGINS) "
                "and run `make analysis-check`."
            )
        if not self.library_path.is_dir():
            raise PiperUnavailable(
                f"Piper runtime libraries not found at {self.library_path}. Restore the "
                "preserved storage/tools/sv/squashfs-root/usr/lib directory."
            )
        if next(self.plugin_path.glob("*.so"), None) is None:
            raise PiperUnavailable(
                f"Vamp plugin pack at {self.plugin_path} contains no *.so plugin libraries. "
                "Restore the preserved pack from storage/tools/plugins."
            )


@dataclass(frozen=True)
class PluginInfo:
    """One entry from the Piper ``list`` response."""

    display_name: str
    key: str
    version: str
    output_ids: tuple[str, ...]


@dataclass(frozen=True)
class LoadedPlugin:
    """A plugin loaded and configured in a :class:`PiperSession`."""

    display_name: str
    key: str
    version: str
    handle: int
    block_size: int
    step_size: int
    parameters: Mapping[str, float]


ProgressCallback = Callable[[str, int, int], None]
CancelCheck = Callable[[], bool]

FeatureMap = dict[str, list[dict[str, Any]]]


def _normalise_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def _as_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PiperProcessError(f"Piper {label} response is not a JSON object")
    return value


def feature_time(feature: Mapping[str, Any]) -> float:
    """Seconds from a Piper feature's ``timestamp`` object."""
    stamp = feature.get("timestamp")
    if not isinstance(stamp, Mapping):
        return 0.0
    seconds = stamp.get("s", 0)
    nanos = stamp.get("n", 0)
    sec = float(seconds) if isinstance(seconds, (int, float)) else 0.0
    nsec = float(nanos) if isinstance(nanos, (int, float)) else 0.0
    return sec + nsec / 1_000_000_000.0


def feature_label(feature: Mapping[str, Any]) -> str | None:
    """The raw label of a feature, never normalised."""
    label = feature.get("label")
    return label if isinstance(label, str) else None


def feature_values(feature: Mapping[str, Any]) -> tuple[float, ...]:
    """The numeric values of a feature."""
    values = feature.get("featureValues")
    if not isinstance(values, list):
        return ()
    return tuple(float(value) for value in values if isinstance(value, (int, float)))


class PiperSession:
    """One Piper server process, reused for several plugins.

    The session is not thread-safe. Use it as a context manager: a normal exit
    shuts the server down gracefully, an exception kills it.
    """

    def __init__(
        self,
        paths: PiperPaths,
        *,
        timeout_seconds: float = 600.0,
        is_cancelled: CancelCheck | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.paths = paths
        self.timeout_seconds = timeout_seconds
        self.is_cancelled = is_cancelled
        self.on_progress = on_progress
        self._process: subprocess.Popen[bytes] | None = None
        self._stdin: IO[bytes] | None = None
        self._stdout: IO[bytes] | None = None
        self._stderr: IO[bytes] | None = None
        self._plugins: list[PluginInfo] | None = None
        self._request_id = 0

    @property
    def pid(self) -> int | None:
        """The child process id while it is running (used by cancellation tests)."""
        return self._process.pid if self._process is not None else None

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> PiperSession:
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close(kill=exc_type is not None)

    def start(self) -> None:
        if self._process is not None:
            return
        self._check_cancelled()
        self.paths.validate()
        environment = dict(os.environ)
        environment["VAMP_PATH"] = str(self.paths.plugin_path)
        existing = environment.get("LD_LIBRARY_PATH", "")
        environment["LD_LIBRARY_PATH"] = (
            f"{self.paths.library_path}:{existing}" if existing else str(self.paths.library_path)
        )
        # stderr goes to a temporary file, not a pipe: the plugin loader is
        # chatty (missing optional RDF files) and a full pipe would deadlock.
        self._stderr = tempfile.TemporaryFile()  # noqa: SIM115 - lives until close()
        try:
            process = subprocess.Popen(
                [str(self.paths.server), "json"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                env=environment,
                bufsize=0,
            )
        except OSError as error:
            self._close_stderr()
            raise PiperUnavailable(
                f"cannot start Piper server {self.paths.server}: {error}"
            ) from error
        self._process = process
        self._stdin = process.stdin
        self._stdout = process.stdout
        if self._stdin is None or self._stdout is None:
            self.close(kill=True)
            raise PiperProcessError("Piper server did not expose stdin/stdout")

    def close(self, *, kill: bool = False) -> None:
        """Stop the server, killing it when cancellation or an error needs it."""
        process = self._process
        if process is not None:
            if self._stdin is not None:
                with contextlib.suppress(OSError):
                    self._stdin.close()
                self._stdin = None
            if process.poll() is None:
                try:
                    if kill:
                        process.kill()
                    else:
                        process.terminate()
                    process.wait(timeout=3)
                except (subprocess.TimeoutExpired, ProcessLookupError):
                    process.kill()
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=3)
            self._process = None
            self._stdout = None
        self._close_stderr()

    def _close_stderr(self) -> None:
        if self._stderr is not None:
            with contextlib.suppress(OSError):
                self._stderr.close()
            self._stderr = None

    # -- protocol ----------------------------------------------------------

    def _check_cancelled(self) -> None:
        if self.is_cancelled is not None and self.is_cancelled():
            raise AnalysisCancelled("analysis cancelled")

    def _stderr_tail(self) -> str:
        stream = self._stderr
        if stream is None:
            return ""
        try:
            stream.flush()
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - STDERR_TAIL_LIMIT))
            text = stream.read().decode("utf-8", "replace").strip()
        except (OSError, ValueError):
            return ""
        if not text:
            return ""
        return f"\nPiper stderr tail:\n{text}"

    def _fail(self, message: str, *, kill: bool = True) -> PiperError:
        detail = message + self._stderr_tail()
        if kill:
            self.close(kill=True)
        return PiperError(detail)

    def _readline(self, deadline: float) -> bytes:
        stream = self._stdout
        if stream is None:
            raise self._fail("Piper server has no stdout")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PiperTimeout(
                "Piper server timed out waiting for a response" + self._stderr_tail()
            )
        ready, _, _ = select.select([stream], [], [], remaining)
        if not ready:
            raise PiperTimeout(
                f"Piper server timed out after {self.timeout_seconds:g} s without an answer"
                + self._stderr_tail()
            )
        line = stream.readline()
        if not line:
            process = self._process
            code = process.poll() if process is not None else None
            status = f"exit status {code}" if code is not None else "closed stdout"
            raise PiperProcessError(
                f"Piper server stopped unexpectedly ({status})" + self._stderr_tail()
            )
        return line

    def request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> Mapping[str, Any]:
        """Send one request and return its ``result`` object."""
        self._check_cancelled()
        if self._process is None or self._stdin is None:
            raise PiperError("Piper session is not started")
        deadline = time.monotonic() + (
            self.timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        self._request_id += 1
        message = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": dict(params),
        }
        try:
            self._stdin.write(json.dumps(message, ensure_ascii=True).encode("utf-8") + b"\n")
            self._stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise self._fail(f"cannot write to the Piper server: {error}") from error
        try:
            line = self._readline(deadline)
        except PiperError:
            self.close(kill=True)
            raise
        try:
            response = json.loads(line.decode("latin-1"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise self._fail(f"Piper server returned invalid JSON: {line[:200]!r}") from error
        if not isinstance(response, Mapping):
            raise self._fail("Piper server returned a non-object response")
        response_error = response.get("error")
        if isinstance(response_error, Mapping):
            message_text = response_error.get("message", "unknown Piper error")
            raise self._fail(f"Piper {method} failed: {message_text}")
        if response_error is not None:
            raise self._fail(f"Piper {method} failed: {response_error}")
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise self._fail(f"Piper {method} response has no result object")
        self._check_cancelled()
        return result

    # -- plugin discovery --------------------------------------------------

    def list_plugins(self) -> list[PluginInfo]:
        """Return the plugins available in ``VAMP_PATH`` (listed once)."""
        if self._plugins is not None:
            return self._plugins
        result = self.request("list", {})
        available = result.get("available")
        if not isinstance(available, list):
            raise self._fail("Piper list response has no available list")
        plugins: list[PluginInfo] = []
        for entry in available:
            if not isinstance(entry, Mapping):
                continue
            basic = entry.get("basic")
            if not isinstance(basic, Mapping):
                continue
            name = basic.get("name")
            key = entry.get("key")
            if not isinstance(name, str) or not isinstance(key, str):
                continue
            version = entry.get("version")
            outputs = entry.get("basicOutputInfo")
            output_ids: list[str] = []
            if isinstance(outputs, list):
                for output in outputs:
                    if isinstance(output, Mapping):
                        identifier = output.get("identifier")
                        if isinstance(identifier, str):
                            output_ids.append(identifier)
            plugins.append(
                PluginInfo(
                    display_name=name,
                    key=key,
                    version=str(version) if isinstance(version, (str, int)) else "",
                    output_ids=tuple(output_ids),
                )
            )
        if not plugins:
            raise self._fail(f"Vamp plugin pack at {self.paths.plugin_path} exposes no plugins")
        self._plugins = plugins
        return plugins

    def resolve(self, display_name: str) -> PluginInfo:
        """Resolve by display name, falling back to the known embed keys."""
        wanted = _normalise_name(display_name)
        plugins = self.list_plugins()
        for plugin in plugins:
            if _normalise_name(plugin.display_name) == wanted:
                return plugin
        known_keys = FALLBACK_KEYS.get(display_name, ())
        for plugin in plugins:
            if plugin.key in known_keys:
                return plugin
        found = ", ".join(plugin.display_name for plugin in plugins[:12])
        raise PiperUnavailable(
            f"Vamp plugin {display_name!r} is not available in {self.paths.plugin_path}"
            + (f" (found: {found}, ...)" if found else "")
            + ". Restore the preserved plugin pack; this build resolves plugins by display "
            "name and only falls back to the recorded embed keys."
        )

    # -- plugin execution --------------------------------------------------

    def load(
        self,
        display_name: str,
        *,
        sample_rate: int,
        parameters: Mapping[str, float] | None = None,
    ) -> LoadedPlugin:
        """Load and configure one plugin at the requested sample rate."""
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        info = self.resolve(display_name)
        result = self.request(
            "load",
            {
                "key": info.key,
                "inputSampleRate": int(sample_rate),
                "adapterFlags": list(ADAPTER_FLAGS),
            },
        )
        configuration = result.get("defaultConfiguration")
        if not isinstance(configuration, Mapping):
            raise self._fail(f"Piper load for {display_name} returned no default configuration")
        handle = result.get("handle")
        if not isinstance(handle, int):
            raise self._fail(f"Piper load for {display_name} returned no handle")
        config = dict(configuration)
        parameter_values = config.get("parameterValues")
        values = dict(parameter_values) if isinstance(parameter_values, Mapping) else {}
        for name, value in (parameters or {}).items():
            if name in values:
                values[name] = float(value)
            else:
                raise PiperProcessError(
                    f"plugin {display_name!r} has no parameter {name!r}; "
                    f"available: {', '.join(sorted(values)) or 'none'}"
                )
        config["parameterValues"] = values
        configured = self.request("configure", {"handle": handle, "configuration": config})
        framing = configured.get("framing")
        if not isinstance(framing, Mapping):
            raise self._fail(f"Piper configure for {display_name} returned no framing")
        block_size = framing.get("blockSize")
        step_size = framing.get("stepSize")
        if not isinstance(block_size, int) or not isinstance(step_size, int):
            raise self._fail(f"Piper configure for {display_name} returned invalid framing")
        if block_size <= 0 or step_size <= 0:
            raise self._fail(f"Piper configure for {display_name} returned non-positive framing")
        static = result.get("staticData")
        version = ""
        if isinstance(static, Mapping):
            raw_version = static.get("version")
            if isinstance(raw_version, (str, int)):
                version = str(raw_version)
        plugin_parameters = {
            name: float(value) for name, value in values.items() if isinstance(value, (int, float))
        }
        return LoadedPlugin(
            display_name=info.display_name,
            key=info.key,
            version=version,
            handle=handle,
            block_size=block_size,
            step_size=step_size,
            parameters=plugin_parameters,
        )

    def feed(
        self,
        plugin: LoadedPlugin,
        signal: NDArray[np.float32],
        *,
        sample_rate: int,
    ) -> FeatureMap:
        """Feed a mono signal in the plugin's preferred blocks."""
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if signal.ndim != 1:
            raise ValueError("signal must be mono (one-dimensional)")
        features: FeatureMap = {}
        total = int(signal.shape[0])
        block_size = plugin.block_size
        step_size = plugin.step_size
        for start in range(0, total, step_size):
            self._check_cancelled()
            block = np.zeros(block_size, dtype=np.float32)
            available = signal[start : start + block_size]
            block[: available.shape[0]] = available
            # Base64 is the protocol's string form for float32 input buffers.
            encoded = base64.b64encode(block.astype("<f4", copy=False).tobytes()).decode("ascii")
            result = self.request(
                "process",
                {
                    "handle": plugin.handle,
                    "processInput": {
                        "inputBuffers": [encoded],
                        "timestamp": {
                            "s": start // sample_rate,
                            "n": (start % sample_rate) * 1_000_000_000 // sample_rate,
                        },
                    },
                },
            )
            self._collect(result, features)
            if self.on_progress is not None:
                self.on_progress(plugin.display_name, min(total, start + step_size), total)
            if start + step_size >= total:
                break
        return features

    def finish(self, plugin: LoadedPlugin) -> FeatureMap:
        """Flush the plugin and return the remaining features."""
        features: FeatureMap = {}
        result = self.request("finish", {"handle": plugin.handle})
        self._collect(result, features)
        return features

    @staticmethod
    def _collect(result: Mapping[str, Any], features: FeatureMap) -> None:
        batch = result.get("features")
        if not isinstance(batch, Mapping):
            return
        for identifier, rows in batch.items():
            if not isinstance(identifier, str) or not isinstance(rows, list):
                continue
            target = features.setdefault(identifier, [])
            for row in rows:
                if isinstance(row, Mapping):
                    target.append(dict(row))

    def analyze(
        self,
        display_name: str,
        signal: NDArray[np.float32],
        *,
        sample_rate: int,
        parameters: Mapping[str, float] | None = None,
    ) -> tuple[LoadedPlugin, FeatureMap]:
        """Load, feed and flush one plugin in a single call."""
        plugin = self.load(display_name, sample_rate=sample_rate, parameters=parameters)
        features = self.feed(plugin, signal, sample_rate=sample_rate)
        finished = self.finish(plugin)
        for identifier, rows in finished.items():
            features.setdefault(identifier, []).extend(rows)
        return plugin, features
