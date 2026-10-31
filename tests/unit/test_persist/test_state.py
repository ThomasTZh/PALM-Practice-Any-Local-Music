"""Project persistence: versioned state, reopen and debounced autosave."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from basseparate.persist import (
    CURRENT_STATE_VERSION,
    DebouncedAutosave,
    MissingAssetError,
    PracticeState,
    ProjectPersistence,
    StateVersionError,
    restore_state,
)
from basseparate.projects import (
    Project,
    ProjectStore,
    build_audio_info,
    build_project,
)

FRAMES = 48_000
RATE = 48_000
CHANNELS = 2


def make_project(
    tmp_path: Path,
    *,
    project_id: str = "practice-1",
    asset_id: str = "asset-main",
) -> tuple[ProjectStore, ProjectPersistence, Project]:
    data = tmp_path / "data"
    store = ProjectStore(data / "projects")
    persistence = ProjectPersistence(store, data / "assets")
    audio = build_audio_info(
        asset_id=asset_id,
        source_name="take.wav",
        source_format="wav",
        sample_rate=RATE,
        channels=CHANNELS,
        frames=FRAMES,
        content_sha256="a" * 64,
        peak_counts={256: 188, 1024: 47},
    )
    project = build_project(audio, name="Practice take", project_id=project_id)
    store.create(project)
    asset_dir = data / "assets" / asset_id
    asset_dir.mkdir(parents=True)
    (asset_dir / "source.wav").write_bytes(b"RIFF")
    (asset_dir / "pcm.f32").write_bytes(b"\0" * (FRAMES * CHANNELS * 4))
    for bucket, count in ((256, 188), (1024, 47)):
        (asset_dir / f"peaks-{bucket}.bin").write_bytes(b"BSPK" + b"\0" * (count * 4))
    return store, persistence, project


def saved_state() -> PracticeState:
    return PracticeState(
        sections=[
            {"id": "s1", "name": "Verse", "start_bar": 1, "end_bar": 8},
            {"id": "s2", "name": "Chorus", "start_bar": 9, "end_bar": 16},
        ],
        loop={"start_frame": 12_000, "end_frame": 36_000, "repeat_count": 4, "fade": True},
        speed=0.75,
        pitch_semitones=-2.0,
        position_frame=12_345,
        analysis={
            "cache_key": "abc123",
            "source_sha256": "a" * 64,
            "sample_rate": 48_000,
            "bpm": 120.0,
            "key": "C major",
        },
        mixer={"bass": {"gain": 0.6, "muted": False, "solo": True}},
    )


def test_save_and_reopen_restores_every_practice_field(tmp_path: Path) -> None:
    store, persistence, project = make_project(tmp_path)
    updated = persistence.save_state(project.id, saved_state())
    assert updated.revision == 2

    reopened = ProjectPersistence(
        ProjectStore(tmp_path / "data" / "projects"), tmp_path / "data" / "assets"
    ).reopen(project.id)
    state = reopened.state
    assert [(s.id, s.name, s.start_bar, s.end_bar) for s in state.sections] == [
        ("s1", "Verse", 1, 8),
        ("s2", "Chorus", 9, 16),
    ]
    assert state.loop is not None
    assert (state.loop.start_frame, state.loop.end_frame, state.loop.repeat_count) == (
        12_000,
        36_000,
        4,
    )
    assert state.speed == 0.75
    assert state.pitch_semitones == -2.0
    assert state.position_frame == 12_345
    assert state.analysis is not None
    assert state.analysis.cache_key == "abc123"
    assert state.analysis.bpm == 120.0
    assert state.analysis.key == "C major"
    assert state.mixer["bass"].gain == 0.6
    assert state.mixer["bass"].solo is True
    assert reopened.project.document["state_version"] == CURRENT_STATE_VERSION


def test_reopen_after_a_new_service_instance_uses_only_the_data_directory(tmp_path: Path) -> None:
    store, persistence, project = make_project(tmp_path)
    persistence.save_state(project.id, saved_state())

    # Simulate a process restart: a fresh store and persistence over the same root.
    restarted = ProjectPersistence(
        ProjectStore(tmp_path / "data" / "projects"), tmp_path / "data" / "assets"
    )
    reopened = restarted.reopen(project.id)
    assert reopened.project.name == "Practice take"
    assert reopened.state.loop is not None
    assert reopened.state.sections[1].name == "Chorus"


def test_missing_asset_is_a_clear_error_but_the_project_stays_readable(tmp_path: Path) -> None:
    store, persistence, project = make_project(tmp_path)
    persistence.save_state(project.id, saved_state())
    (tmp_path / "data" / "assets" / "asset-main" / "pcm.f32").unlink()

    with pytest.raises(MissingAssetError, match="missing") as error:
        persistence.reopen(project.id)
    assert project.id in str(error.value)
    assert "asset-main" in str(error.value)
    # The JSON is untouched and still readable through the store and the state view.
    assert store.get(project.id).name == "Practice take"
    assert persistence.load_state(project.id).state.speed == 0.75
    assert "pcm.f32" in persistence.missing_assets(store.get(project.id))[0]


def test_legacy_documents_are_migrated_and_future_versions_are_rejected(tmp_path: Path) -> None:
    legacy = {
        "sections": [{"id": "s1", "name": "Old", "start_bar": 1, "end_bar": 4}],
        "loop": {"start_frame": 100, "end_frame": 900},
        "speed": 1.25,
        "pitch": -5,
        "analysis": "cache-key-only",
    }
    state = restore_state(legacy)
    assert state.speed == 1.25
    assert state.pitch_semitones == -5
    assert state.sections[0].name == "Old"
    assert state.analysis is not None
    assert state.analysis.cache_key == "cache-key-only"

    with pytest.raises(StateVersionError, match="newer"):
        restore_state({"state_version": CURRENT_STATE_VERSION + 1})


def test_out_of_range_controls_are_clamped_on_restore(tmp_path: Path) -> None:
    state = restore_state({"speed": 99, "pitch_semitones": -99, "position_frame": -3})
    assert state.speed == 2.0
    assert state.pitch_semitones == -12.0
    assert state.position_frame == 0


class FakeTimer:
    def __init__(self, delay: float, callback) -> None:
        self.delay = delay
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


class FakeScheduler:
    def __init__(self) -> None:
        self.timers: list[FakeTimer] = []

    def __call__(self, delay: float, callback) -> FakeTimer:
        timer = FakeTimer(delay, callback)
        self.timers.append(timer)
        return timer

    def fire_all(self) -> None:
        for timer in list(self.timers):
            timer.fire()


def test_autosave_is_debounced_to_the_latest_state(tmp_path: Path) -> None:
    store, persistence, project = make_project(tmp_path)
    scheduler = FakeScheduler()
    autosave = DebouncedAutosave(persistence, project.id, delay_seconds=0.25, scheduler=scheduler)
    autosave.schedule(PracticeState(speed=0.5))
    autosave.schedule(PracticeState(speed=1.5, position_frame=99))
    assert store.get(project.id).revision == 1
    assert len(scheduler.timers) == 2
    assert scheduler.timers[0].cancelled is True

    scheduler.timers[-1].fire()
    assert autosave.last_error is None
    assert store.get(project.id).revision == 2
    reopened = persistence.reopen(project.id)
    assert reopened.state.speed == 1.5
    assert reopened.state.position_frame == 99
    assert autosave.pending is False


def test_autosave_crash_mid_write_keeps_the_previous_project(tmp_path: Path, monkeypatch) -> None:
    store, persistence, project = make_project(tmp_path)
    persistence.save_state(project.id, saved_state())
    before = (tmp_path / "data" / "projects" / f"{project.id}.json").read_bytes()

    import basseparate.projects as projects_module

    def explode(*args, **kwargs):
        raise OSError("simulated autosave crash")

    monkeypatch.setattr(projects_module.os, "replace", explode)
    with pytest.raises(OSError, match="simulated autosave crash"):
        persistence.save_state(project.id, PracticeState(speed=0.5))
    monkeypatch.undo()

    assert (tmp_path / "data" / "projects" / f"{project.id}.json").read_bytes() == before
    assert store.get(project.id).document["speed"] == 0.75
    assert list((tmp_path / "data" / "projects").glob(".*.tmp")) == []


def test_autosave_records_errors_and_retries_with_flush(tmp_path: Path, monkeypatch) -> None:
    _store, persistence, project = make_project(tmp_path)
    scheduler = FakeScheduler()
    autosave = DebouncedAutosave(persistence, project.id, scheduler=scheduler)
    autosave.schedule(PracticeState(speed=0.5))

    import basseparate.projects as projects_module

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(projects_module.os, "replace", explode)
    scheduler.fire_all()
    assert autosave.last_error is not None
    assert "disk full" in autosave.last_error
    monkeypatch.undo()

    saved = autosave.flush()
    assert saved is not None
    assert saved.document["speed"] == 0.5
    assert autosave.last_error is None


def test_state_save_is_revision_checked(tmp_path: Path) -> None:
    _store, persistence, project = make_project(tmp_path)
    from basseparate.projects import RevisionConflict

    persistence.save_state(project.id, PracticeState(speed=0.5), expected_revision=1)
    with pytest.raises(RevisionConflict):
        persistence.save_state(project.id, PracticeState(speed=1.5), expected_revision=1)


def test_project_json_is_valid_after_state_save(tmp_path: Path) -> None:
    _store, persistence, project = make_project(tmp_path)
    persistence.save_state(project.id, saved_state())
    document = json.loads((tmp_path / "data" / "projects" / f"{project.id}.json").read_text())
    assert document["document"]["state_version"] == CURRENT_STATE_VERSION
    assert document["document"]["sections"][0]["start_bar"] == 1
