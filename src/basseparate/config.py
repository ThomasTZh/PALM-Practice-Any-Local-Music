"""Typed application configuration.

Precedence (highest first): explicit CLI argument, ``BASSEPARATE_`` environment
variable, user TOML configuration, built-in default.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir

from basseparate import APP_NAME

ENV_PREFIX = "BASSEPARATE_"

LOOPBACK_ADDRESSES = frozenset({"127.0.0.1", "::1"})
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class ConfigError(ValueError):
    """Raised when the resolved configuration is invalid."""


@dataclass(frozen=True, slots=True)
class AppConfig:
    bind_address: str
    port: int
    open_browser: bool
    offline_mode: bool
    log_level: str
    development_mode: bool
    startup_timeout_seconds: float
    worker_handshake_timeout_seconds: float
    worker_graceful_stop_timeout_seconds: float
    database_busy_timeout_seconds: float
    storage_root: Path | None
    config_file: Path

    def describe_for_log(self) -> str:
        """Effective configuration with no secrets (tokens never live here)."""

        return (
            f"bind={self.bind_address}:{self.port} "
            f"open_browser={self.open_browser} offline_mode={self.offline_mode} "
            f"log_level={self.log_level} development_mode={self.development_mode} "
            f"startup_timeout={self.startup_timeout_seconds}s "
            f"worker_handshake_timeout={self.worker_handshake_timeout_seconds}s "
            f"worker_graceful_stop_timeout={self.worker_graceful_stop_timeout_seconds}s "
            f"database_busy_timeout={self.database_busy_timeout_seconds}s "
            f"storage_root={self.storage_root}"
        )


def user_config_file() -> Path:
    return Path(user_config_dir(APP_NAME)) / "config.toml"


@dataclass(frozen=True)
class _FieldSpec:
    name: str
    kind: type  # int, float, bool, or str
    default: object

    def env_name(self) -> str:
        return ENV_PREFIX + self.name.upper()


_FIELDS: tuple[_FieldSpec, ...] = (
    _FieldSpec("bind_address", str, "127.0.0.1"),
    _FieldSpec("port", int, 8765),
    _FieldSpec("open_browser", bool, True),
    _FieldSpec("offline_mode", bool, True),
    _FieldSpec("log_level", str, "INFO"),
    _FieldSpec("development_mode", bool, False),
    _FieldSpec("startup_timeout_seconds", float, 15.0),
    _FieldSpec("worker_handshake_timeout_seconds", float, 5.0),
    _FieldSpec("worker_graceful_stop_timeout_seconds", float, 5.0),
    _FieldSpec("database_busy_timeout_seconds", float, 5.0),
)


def _coerce(spec: _FieldSpec, raw: object, source: str) -> object:
    if spec.kind is str:
        if not isinstance(raw, str):
            raise ConfigError(f"{spec.name} must be a string, got {raw!r} ({source})")
        return raw
    if spec.kind is int:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ConfigError(f"{spec.name} must be an integer, got {raw!r} ({source})")
        return raw
    if spec.kind is float:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ConfigError(f"{spec.name} must be a number, got {raw!r} ({source})")
        return float(raw)
    if spec.kind is bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            lowered = raw.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
        raise ConfigError(f"{spec.name} must be a boolean, got {raw!r} ({source})")
    raise ConfigError(f"unsupported field type for {spec.name}")  # defensive


def _read_toml(config_file: Path) -> dict[str, object]:
    if not config_file.is_file():
        return {}
    try:
        with config_file.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {config_file}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"top level of {config_file} must be a table")
    return data


def _validate(values: dict[str, object]) -> None:
    port = values["port"]
    assert isinstance(port, int)
    if not 1 <= port <= 65535:
        raise ConfigError(f"port must be between 1 and 65535, got {port}")

    address = values["bind_address"]
    assert isinstance(address, str)
    if address not in LOOPBACK_ADDRESSES:
        raise ConfigError(
            f"bind_address must be a loopback address ({', '.join(sorted(LOOPBACK_ADDRESSES))}), "
            f"got {address!r}; LAN binding is not permitted"
        )

    level = values["log_level"]
    assert isinstance(level, str)
    normalized = level.strip().upper()
    if normalized not in LOG_LEVELS:
        raise ConfigError(
            f"log_level must be one of {', '.join(sorted(LOG_LEVELS))}, got {level!r}"
        )
    values["log_level"] = normalized

    for name in (
        "startup_timeout_seconds",
        "worker_handshake_timeout_seconds",
        "worker_graceful_stop_timeout_seconds",
        "database_busy_timeout_seconds",
    ):
        value = values[name]
        assert isinstance(value, float)
        if value <= 0:
            raise ConfigError(f"{name} must be positive, got {value}")

    root = values["storage_root"]
    if root is not None:
        if not isinstance(root, (str, Path)):
            raise ConfigError(f"storage_root must be a path, got {root!r}")
        resolved = Path(root)
        if resolved.exists() and not resolved.is_dir():
            raise ConfigError(f"storage_root must be a directory, got file: {resolved}")
        values["storage_root"] = resolved


def resolve_config(
    cli: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
    config_file: Path | None = None,
) -> AppConfig:
    """Resolve the effective configuration and validate it."""

    config_file = config_file if config_file is not None else user_config_file()
    values: dict[str, object] = {spec.name: spec.default for spec in _FIELDS}
    values["storage_root"] = None
    values["config_file"] = config_file

    toml_values = _read_toml(config_file)
    for key, raw in toml_values.items():
        spec = next((s for s in _FIELDS if s.name == key), None)
        if spec is None:
            if key == "storage_root":
                values["storage_root"] = raw
            continue
        values[spec.name] = _coerce(spec, raw, f"TOML {config_file}")

    environment = os.environ if env is None else env
    for spec in _FIELDS:
        raw = environment.get(spec.env_name())
        if raw is None:
            continue
        if spec.kind is int:
            try:
                parsed: object = int(raw)
            except ValueError as exc:
                raise ConfigError(f"{spec.env_name()} must be an integer, got {raw!r}") from exc
        elif spec.kind is float:
            try:
                parsed = float(raw)
            except ValueError as exc:
                raise ConfigError(f"{spec.env_name()} must be a number, got {raw!r}") from exc
        else:
            parsed = raw
        values[spec.name] = _coerce(spec, parsed, f"env {spec.env_name()}")

    for key, raw in (cli or {}).items():
        if raw is None:
            continue
        if key == "storage_root":
            values["storage_root"] = Path(raw) if isinstance(raw, str) else raw
            continue
        spec = next((s for s in _FIELDS if s.name == key), None)
        if spec is None:
            raise ConfigError(f"unknown configuration option: {key!r}")
        values[key] = _coerce(spec, raw, f"CLI --{key}")

    _validate(values)
    return AppConfig(**values)  # type: ignore[arg-type]
