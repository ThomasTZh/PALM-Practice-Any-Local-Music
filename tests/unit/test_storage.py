"""Unit tests for storage path layout and initialization (M0.3)."""

from __future__ import annotations

import stat

import pytest

from basseparate.storage import (
    StorageError,
    default_storage_paths,
    initialize_storage_paths,
    resolve_storage_paths,
)


def test_default_paths_follow_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    paths = default_storage_paths()
    assert paths.config == tmp_path / "cfg" / "basseparate"
    assert paths.data == tmp_path / "data" / "basseparate"
    assert paths.cache == tmp_path / "cache" / "basseparate"
    assert paths.state == tmp_path / "state" / "basseparate"
    assert paths.runtime == tmp_path / "state" / "basseparate" / "runtime"
    assert paths.database_path == tmp_path / "data" / "basseparate" / "basseparate.db"


def test_explicit_storage_root_places_all_categories(tmp_path) -> None:
    paths = resolve_storage_paths(tmp_path / "root")
    assert paths.config == tmp_path / "root" / "config"
    assert paths.data == tmp_path / "root" / "data"
    assert paths.cache == tmp_path / "root" / "cache"
    assert paths.state == tmp_path / "root" / "state"
    assert paths.runtime == tmp_path / "root" / "runtime"


def test_initialize_creates_directories_with_owner_only_sensitive_dirs(tmp_path) -> None:
    paths = resolve_storage_paths(tmp_path / "root")
    initialize_storage_paths(paths)
    for directory in (paths.config, paths.data, paths.cache, paths.state, paths.runtime):
        assert directory.is_dir()
    mode = stat.S_IMODE(paths.data.stat().st_mode)
    assert mode == stat.S_IRWXU
    mode_runtime = stat.S_IMODE(paths.runtime.stat().st_mode)
    assert mode_runtime == stat.S_IRWXU

    # Idempotent: a second call does not fail and does not clear contents.
    marker = paths.data / "keep.txt"
    marker.write_text("user data", encoding="utf-8")
    initialize_storage_paths(paths)
    assert marker.read_text(encoding="utf-8") == "user data"


def test_initialize_refuses_path_blocked_by_file(tmp_path) -> None:
    blocker = tmp_path / "root" / "data"
    blocker.parent.mkdir(parents=True)
    blocker.write_text("i am a file", encoding="utf-8")
    paths = resolve_storage_paths(tmp_path / "root")
    with pytest.raises(StorageError, match="not a directory"):
        initialize_storage_paths(paths)


def test_initialize_refuses_unwritable_directory(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    root.chmod(stat.S_IRUSR | stat.S_IXUSR)  # read/execute only
    try:
        paths = resolve_storage_paths(root)
        with pytest.raises(StorageError):
            initialize_storage_paths(paths)
    finally:
        root.chmod(stat.S_IRWXU)


def test_initialize_never_deletes_existing_content(tmp_path) -> None:
    root = tmp_path / "root"
    (root / "data" / "sub").mkdir(parents=True)
    (root / "data" / "sub" / "file.bin").write_bytes(b"\x00" * 16)
    paths = resolve_storage_paths(root)
    initialize_storage_paths(paths)
    assert (root / "data" / "sub" / "file.bin").read_bytes() == b"\x00" * 16
