"""Update staging, external swap/rollback and uninstall data choices."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest

from basseparate.updater import (
    InstallMetadata,
    UninstallPlan,
    UpdateAsset,
    UpdateError,
    check_for_update,
    default_delete_data,
    helper_path,
    launch_helper,
    load_metadata,
    select_update,
    stage_update,
    write_plan,
    write_uninstall_plan,
)


def asset(data: bytes = b"new app", *, sha: str | None = None) -> UpdateAsset:
    return UpdateAsset(
        channel="linux-x86_64",
        version="0.2.0",
        name="PALM-0.2.0-linux-x86_64.tar.gz",
        url="https://example.invalid/PALM-0.2.0-linux-x86_64.tar.gz",
        sha256=sha or hashlib.sha256(data).hexdigest(),
        kind="tar.gz",
    )


def metadata(tmp_path: Path, *, channel: str = "linux-x86_64") -> InstallMetadata:
    app = tmp_path / "PALM app ü"
    data = tmp_path / "data"
    app.mkdir()
    data.mkdir()
    installed = asset()
    return InstallMetadata(
        channel=channel,
        version="0.1.0",
        app_root=app,
        data_root=data,
        assets={channel: installed},
    )


def load_helper(name: str = "update_helper") -> Any:
    path = Path(__file__).resolve().parents[3] / "packaging/updaters/update_helper.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_metadata_and_channel_asset_selection(tmp_path: Path) -> None:
    meta = metadata(tmp_path)
    release = {
        "version": "0.2.0",
        "channels": {
            "linux-x86_64": {
                "version": "0.2.0",
                "name": "PALM-0.2.0-linux-x86_64.tar.gz",
                "url": "https://example.invalid/new.tar.gz",
                "sha256": "a" * 64,
                "kind": "tar.gz",
            },
            "windows-x86_64": {
                "version": "0.2.0",
                "name": "PALM-0.2.0-windows-x86_64.zip",
                "url": "https://example.invalid/new.zip",
                "sha256": "b" * 64,
                "kind": "zip",
            },
        },
    }
    selected = select_update(meta, release)
    assert selected is not None
    assert selected.name.endswith("linux-x86_64.tar.gz")
    assert check_for_update(meta, fetch_release=lambda _url: release) == selected
    release["channels"]["linux-x86_64"]["version"] = "0.1.0"
    assert select_update(meta, release) is None
    with pytest.raises(UpdateError, match="https"):
        select_update(
            meta,
            {"channels": {"linux-x86_64": {"name": "x", "url": "file:///x", "sha256": "a" * 64}}},
        )


def test_stage_verifies_checksum_and_never_touches_app(tmp_path: Path) -> None:
    meta = metadata(tmp_path)
    payload = b"verified update"
    candidate = asset(payload)
    app_before = sorted(meta.app_root.iterdir())
    staged = stage_update(
        candidate, meta.data_root, download=lambda _url, path: path.write_bytes(payload)
    )
    assert staged == meta.data_root / "updates" / "0.2.0" / candidate.name
    assert staged.read_bytes() == payload
    assert sorted(meta.app_root.iterdir()) == app_before
    bad = UpdateAsset(
        channel="linux-x86_64",
        version="0.2.0",
        name="PALM-0.2.0-bad-linux-x86_64.tar.gz",
        url="https://example.invalid/bad.tar.gz",
        sha256="0" * 64,
        kind="tar.gz",
    )
    with pytest.raises(UpdateError, match="checksum"):
        stage_update(bad, meta.data_root, download=lambda _url, path: path.write_bytes(b"other"))
    assert not (meta.data_root / "updates" / "0.2.0" / bad.name).exists()


def test_plan_requires_helper_outside_app_and_launches_detached(tmp_path: Path) -> None:
    meta = metadata(tmp_path)
    staged = tmp_path / "data/updates/0.2.0/new.tar.gz"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"x")
    helper = meta.app_root.parent / "palm-update-helper.py"
    helper.write_text("# helper")
    plan = write_plan(meta, asset(), staged, helper)
    payload = json.loads(plan.read_text())
    assert payload["app_root"] == str(meta.app_root)
    assert payload["data_root"] == str(meta.data_root)
    calls: list[list[str]] = []
    launch_helper(plan, popen=lambda command, **kw: calls.append(command))
    assert calls and "--plan" in calls[0]
    inside = meta.app_root / "helper.py"
    inside.write_text("# bad")
    with pytest.raises(UpdateError, match="outside"):
        launch_helper(write_plan(meta, asset(), staged, inside), popen=lambda *a, **k: None)


def test_swap_success_preserves_data_and_restarts(tmp_path: Path) -> None:
    helper = load_helper()
    app = tmp_path / "PALM app ü"
    data = tmp_path / "data"
    app.mkdir()
    data.mkdir()
    (app / "old.txt").write_text("old")
    (data / "projects").mkdir()
    (data / "projects" / "song.json").write_text("keep")
    archive = tmp_path / "new.tar.gz"
    source = tmp_path / "source"
    new_root = source / "PALM-new"
    new_root.mkdir(parents=True)
    (new_root / "new.txt").write_text("new")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(new_root, arcname="PALM-new")
    restarted: list[list[str]] = []
    plan = {
        "app_root": str(app),
        "asset": str(archive),
        "data_root": str(data),
        "kind": "tar.gz",
        "pid": 0,
        "restart": ["palm", "--window"],
    }
    assert helper.swap_app(
        plan, wait=lambda _pid: None, restart=lambda command: restarted.append(command)
    )
    assert (app / "new.txt").read_text() == "new"
    assert not (app / "old.txt").exists()
    assert (data / "projects" / "song.json").read_text() == "keep"
    assert restarted == [["palm", "--window"]]


def test_swap_failure_rolls_back_and_preserves_data(tmp_path: Path) -> None:
    helper = load_helper()
    app = tmp_path / "PALM.app"
    data = tmp_path / "data"
    app.mkdir()
    data.mkdir()
    (app / "old.txt").write_text("old")
    (data / "models").mkdir()
    (data / "models" / "keep.bin").write_bytes(b"keep")
    archive = tmp_path / "bad.zip"
    archive.write_bytes(b"not a zip")
    plan = {
        "app_root": str(app),
        "asset": str(archive),
        "data_root": str(data),
        "kind": "zip",
        "pid": 0,
    }
    assert not helper.swap_app(plan, wait=lambda _pid: None)
    assert (app / "old.txt").read_text() == "old"
    assert (data / "models" / "keep.bin").read_bytes() == b"keep"
    assert not list(tmp_path.glob("PALM.app.palm-backup"))


def test_uninstall_keep_and_delete_data(tmp_path: Path) -> None:
    helper = load_helper()
    app = tmp_path / "PALM app"
    data = tmp_path / "data"
    shortcut = tmp_path / "PALM.desktop"
    app.mkdir()
    data.mkdir()
    (data / "projects").mkdir()
    (data / "projects" / "keep").write_text("keep")
    shortcut.write_text("shortcut")
    plan = {
        "app_root": str(app),
        "data_root": str(data),
        "delete_data": False,
        "pid": 0,
        "shortcuts": [str(shortcut)],
    }
    assert helper.uninstall(plan, wait=lambda _pid: None)
    assert not app.exists()
    assert not shortcut.exists()
    assert (data / "projects" / "keep").exists()
    plan["delete_data"] = True
    helper.uninstall(plan, wait=lambda _pid: None)
    assert not data.exists()


def test_uninstall_plan_and_default_keep(tmp_path: Path) -> None:
    meta = metadata(tmp_path)
    plan = UninstallPlan(meta.app_root, meta.data_root, False, 123, (Path("shortcut"),))
    helper = tmp_path / "uninstall-helper.py"
    path = write_uninstall_plan(plan, helper)
    payload = json.loads(path.read_text())
    assert payload["delete_data"] is False
    assert payload["pid"] == 123
    assert default_delete_data(False) is False
    assert default_delete_data(True) is True


def test_metadata_reports_missing_and_invalid(tmp_path: Path) -> None:
    with pytest.raises(UpdateError, match="cannot read"):
        load_metadata(tmp_path / "missing", tmp_path)
    app = tmp_path / "app"
    app.mkdir()
    (app / "install.json").write_text(json.dumps({"channel": "linux-x86_64"}))
    with pytest.raises(UpdateError, match="channel and version"):
        load_metadata(app, tmp_path)
    assert helper_path(app) == app.parent / "palm-update-helper.py"


def test_uninstall_app_stops_then_launches_external_helper(tmp_path: Path) -> None:
    from basseparate import control

    meta = metadata(tmp_path)
    helper = meta.app_root.parent / "uninstall-helper.py"
    helper.write_text("# helper")
    calls: list[list[str]] = []

    class Controller:
        stopped = 0

        def stop(self) -> None:
            self.stopped += 1

    controller = Controller()
    plan = control.uninstall_app(
        controller,  # type: ignore[arg-type]
        type(
            "Paths",
            (),
            {
                "runtime": type(
                    "Runtime",
                    (),
                    {"app_root": meta.app_root, "data_root": meta.data_root},
                )()
            },
        )(),
        delete_data=False,
        helper=helper,
        popen=lambda command, **kw: calls.append(command),
    )
    assert controller.stopped == 1
    assert calls and "--plan" in calls[0]
    assert plan.read_text().find('"delete_data": false') >= 0
