"""Unit tests for configuration resolution and validation (M0.3, matrix 13.1)."""

from __future__ import annotations

import pytest

from basseparate.config import ConfigError, resolve_config


def test_defaults() -> None:
    config = resolve_config(env={})
    assert config.bind_address == "127.0.0.1"
    assert config.port == 8765
    assert config.open_browser is True
    assert config.offline_mode is True
    assert config.log_level == "INFO"
    assert config.development_mode is False
    assert config.startup_timeout_seconds == 15.0
    assert config.worker_handshake_timeout_seconds == 5.0
    assert config.worker_graceful_stop_timeout_seconds == 5.0
    assert config.database_busy_timeout_seconds == 5.0
    assert config.storage_root is None


def test_precedence_cli_over_env_over_toml(tmp_path) -> None:
    toml = tmp_path / "config.toml"
    toml.write_text('port = 9000\nlog_level = "debug"\n', encoding="utf-8")

    only_toml = resolve_config(env={}, config_file=toml)
    assert only_toml.port == 9000
    assert only_toml.log_level == "DEBUG"

    with_env = resolve_config(env={"BASSEPARATE_PORT": "9001"}, config_file=toml)
    assert with_env.port == 9001

    with_cli = resolve_config(
        cli={"port": 9002}, env={"BASSEPARATE_PORT": "9001"}, config_file=toml
    )
    assert with_cli.port == 9002


def test_env_typed_parsing() -> None:
    config = resolve_config(
        env={
            "BASSEPARATE_PORT": "8080",
            "BASSEPARATE_OPEN_BROWSER": "false",
            "BASSEPARATE_DATABASE_BUSY_TIMEOUT_SECONDS": "2.5",
        }
    )
    assert config.port == 8080
    assert config.open_browser is False
    assert config.database_busy_timeout_seconds == 2.5


def test_cache_limit_bytes_defaults_to_50_gib() -> None:
    from basseparate.config import DEFAULT_CACHE_LIMIT_BYTES

    config = resolve_config(env={})
    assert DEFAULT_CACHE_LIMIT_BYTES == 50 * 1024**3
    assert config.cache_limit_bytes == DEFAULT_CACHE_LIMIT_BYTES


def test_cache_limit_bytes_env_override() -> None:
    config = resolve_config(env={"BASSEPARATE_CACHE_LIMIT_BYTES": str(10 * 1024**3)})
    assert config.cache_limit_bytes == 10 * 1024**3


def test_cache_limit_bytes_below_minimum_rejected() -> None:
    with pytest.raises(ConfigError, match="cache_limit_bytes"):
        resolve_config(env={"BASSEPARATE_CACHE_LIMIT_BYTES": str(1024**2)})  # 1 MiB


def test_invalid_port_values() -> None:
    for bad in ("0", "70000", "abc"):
        with pytest.raises(ConfigError):
            resolve_config(env={"BASSEPARATE_PORT": bad})


def test_invalid_storage_path_points_at_file(tmp_path) -> None:
    a_file = tmp_path / "afile"
    a_file.write_text("x", encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a directory"):
        resolve_config(cli={"storage_root": str(a_file)})


def test_valid_storage_root_dir_accepted(tmp_path) -> None:
    config = resolve_config(cli={"storage_root": str(tmp_path)})
    assert config.storage_root == tmp_path


def test_non_loopback_bind_address_rejected() -> None:
    for bad in ("0.0.0.0", "192.168.1.10"):
        with pytest.raises(ConfigError, match="loopback"):
            resolve_config(env={"BASSEPARATE_BIND_ADDRESS": bad})


def test_invalid_log_level_rejected() -> None:
    with pytest.raises(ConfigError, match="log_level"):
        resolve_config(env={"BASSEPARATE_LOG_LEVEL": "LOUD"})


def test_nonpositive_timeout_rejected() -> None:
    with pytest.raises(ConfigError, match="positive"):
        resolve_config(env={"BASSEPARATE_STARTUP_TIMEOUT_SECONDS": "0"})


def test_unknown_cli_option_rejected() -> None:
    with pytest.raises(ConfigError, match="unknown configuration option"):
        resolve_config(cli={"nonsense": 1})


def test_invalid_toml_file_rejected(tmp_path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("port = ", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid TOML"):
        resolve_config(env={}, config_file=bad)


def test_log_describes_effective_config_without_secrets() -> None:
    config = resolve_config(env={"BASSEPARATE_PORT": "9999"})
    text = config.describe_for_log()
    assert "8765" not in text
    assert "9999" in text
    assert "token" not in text.lower()


def test_media_worker_memory_limit_default_env_and_validation(tmp_path) -> None:
    from basseparate.config import (
        DEFAULT_MEDIA_WORKER_MEMORY_LIMIT_MB,
        MIN_MEDIA_WORKER_MEMORY_LIMIT_MB,
    )

    assert DEFAULT_MEDIA_WORKER_MEMORY_LIMIT_MB == 4096
    assert MIN_MEDIA_WORKER_MEMORY_LIMIT_MB == 256
    config = resolve_config(env={}, config_file=tmp_path / "absent.toml")
    assert config.media_worker_memory_limit_mb == DEFAULT_MEDIA_WORKER_MEMORY_LIMIT_MB
    from_env = resolve_config(
        env={"BASSEPARATE_MEDIA_WORKER_MEMORY_LIMIT_MB": "2048"},
        config_file=tmp_path / "absent.toml",
    )
    assert from_env.media_worker_memory_limit_mb == 2048
    assert "media_worker_memory_limit_mb=2048" in from_env.describe_for_log()
    with pytest.raises(ConfigError, match="media_worker_memory_limit_mb"):
        resolve_config(
            env={"BASSEPARATE_MEDIA_WORKER_MEMORY_LIMIT_MB": "64"},
            config_file=tmp_path / "absent.toml",
        )


def test_relative_storage_root_resolves_to_absolute_paths(tmp_path, monkeypatch) -> None:
    """Workers only accept absolute paths (import/decode job regression)."""
    from pathlib import Path

    from basseparate.storage.paths import resolve_storage_paths

    monkeypatch.chdir(tmp_path)
    paths = resolve_storage_paths(Path("store"))
    for path in (paths.config, paths.data, paths.cache, paths.state, paths.runtime):
        assert path.is_absolute()
    assert paths.data == (tmp_path / "store" / "data").resolve()
