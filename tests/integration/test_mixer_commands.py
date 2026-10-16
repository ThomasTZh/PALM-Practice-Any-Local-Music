"""Integration tests for the stem-mixer commands (M2.8, spec §10.2/§10.3/§10.4/§10.6).

The four mixer ops (``set_track_settings``, ``set_playback_mode``,
``set_master_gain``, ``set_monitoring_limiter``) are undoable commands
on the project's practice state: patch semantics, the
stem-mode-requires-result-set pre-validation, history, and persistence.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from basseparate.domain.commands import (
    SetActiveResultSetOp,
    SetMasterGainOp,
    SetMonitoringLimiterOp,
    SetPlaybackModeOp,
    SetPlaybackSpeedOp,
    SetTrackSettingsOp,
)
from basseparate.domain.practice import (
    MAX_GAIN,
    MAX_PLAYBACK_SPEED,
    MIN_PLAYBACK_SPEED,
    PlaybackMode,
    TrackSettings,
)
from basseparate.domain.separation import (
    DeviceType,
    ReferenceMixIdentity,
    SeparationMode,
    SeparationResultSet,
    SeparationRun,
    SourceIdentity,
    StemRole,
)
from basseparate.storage.db import initialize_database
from basseparate.storage.repository import (
    PlaybackModeRequiresResultSetError,
    ProjectRepository,
    SeparationRepository,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
HASH = "a" * 64
DURATION = 100_000


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "basseparate.db"
    initialize_database(path)
    return path


@pytest.fixture()
def repo(db_path: Path) -> ProjectRepository:
    return ProjectRepository(db_path)


@pytest.fixture()
def separation(db_path: Path) -> SeparationRepository:
    return SeparationRepository(db_path)


def _sql(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _make_ready_project(repo: ProjectRepository, db_path: Path) -> uuid.UUID:
    project = repo.create_project("Ready")
    conn = _sql(db_path)
    try:
        conn.execute(
            """
            UPDATE projects SET
                status = 'ready',
                source_asset_id = ?,
                canonical_asset_id = ?,
                source_stream_index = 0,
                sample_rate = 48000,
                duration_frames = ?,
                source_channel_count = 2,
                source_channel_layout = 'stereo',
                decode_profile_version = 1
            WHERE id = ?
            """,
            (str(uuid4()), str(uuid4()), DURATION, str(project.id)),
        )
        conn.commit()
    finally:
        conn.close()
    return project.id


def _result_set_for(separation: SeparationRepository, project_id: uuid.UUID) -> uuid.UUID:
    """Create a minimal queued run + pending result set for the project."""
    run = SeparationRun(
        id=uuid4(),
        project_id=project_id,
        input_asset_id=uuid4(),
        input_transform_hash=HASH,
        requested_mode=SeparationMode.FOUR_STEMS,
        model_manifest_id=uuid4(),
        model_manifest_hash=HASH,
        engine_version="demucs-4.1.0",
        adapter_version="adapter-1",
        device_type=DeviceType.CPU,
    )
    separation.create_run(run)
    result_set = SeparationResultSet(
        id=uuid4(),
        run_id=run.id,
        project_id=project_id,
        source=SourceIdentity(
            asset_id=uuid4(), source_hash=HASH, sample_rate=48_000, duration_frames=DURATION
        ),
        output_sample_rate=48_000,
        output_channel_count=2,
        output_frame_count=DURATION,
        reference_mix=ReferenceMixIdentity(
            asset_id=uuid4(), hash=HASH, transformation_hash=HASH
        ),
        created_at=NOW,
    )
    separation.create_result_set(result_set)
    return result_set.id


def _current(repo: ProjectRepository, project_id: uuid.UUID):
    project = repo.get_project(project_id)
    assert project is not None
    return project


def _activate_set(repo: ProjectRepository, project_id: uuid.UUID, rs_id: uuid.UUID):
    project = _current(repo, project_id)
    return repo.apply_command(
        project_id, SetActiveResultSetOp(result_set_id=rs_id), project.revision
    )


class TestSetTrackSettings:
    def test_creates_entry_with_defaults_and_patches(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        base = _current(repo, project_id).revision

        result = repo.apply_command(
            project_id,
            SetTrackSettingsOp(stem_role=StemRole.BASS, gain=0.5, color="#112233"),
            base,
        )

        track = result.practice_state.tracks["bass"]
        assert track.gain == 0.5
        assert track.color == "#112233"
        # Untouched fields keep the TrackSettings defaults.
        assert track.mute is False
        assert track.balance == 0.0
        assert track.visible is True
        assert track.display_height == 1.0
        assert result.revision == base + 1
        assert result.can_undo is True

    def test_patch_preserves_existing_fields(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        project = _current(repo, project_id)
        project = repo.apply_command(
            project_id,
            SetTrackSettingsOp(stem_role=StemRole.BASS, gain=0.5, mute=True),
            project.revision,
        )
        project = repo.apply_command(
            project_id, SetTrackSettingsOp(stem_role=StemRole.BASS, solo=True), project.revision
        )

        track = project.practice_state.tracks["bass"]
        assert track.gain == 0.5
        assert track.mute is True
        assert track.solo is True

    def test_undo_and_redo(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        project = _current(repo, project_id)
        assert project.practice_state.tracks == {}

        project = repo.apply_command(
            project_id,
            SetTrackSettingsOp(stem_role=StemRole.BASS, gain=2.0),
            project.revision,
        )
        assert project.practice_state.tracks["bass"].gain == 2.0

        project = repo.undo(project_id, project.revision)
        assert project.practice_state.tracks == {}
        assert project.can_redo is True

        project = repo.redo(project_id, project.revision)
        assert project.practice_state.tracks["bass"].gain == 2.0

    def test_persists_across_reopen(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        project = _current(repo, project_id)
        project = repo.apply_command(
            project_id,
            SetTrackSettingsOp(stem_role=StemRole.VOCALS, mute=True, color="#ABCDEF"),
            project.revision,
        )

        reopened = ProjectRepository(db_path)
        restored = _current(reopened, project_id)
        assert restored.practice_state.tracks["vocals"].mute is True
        assert restored.practice_state.tracks["vocals"].color == "#ABCDEF"


class TestSetPlaybackMode:
    def test_stem_mode_with_active_set_applies(
        self, repo: ProjectRepository, separation: SeparationRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        rs_id = _result_set_for(separation, project_id)
        _activate_set(repo, project_id, rs_id)
        base = _current(repo, project_id).revision

        result = repo.apply_command(
            project_id, SetPlaybackModeOp(mode=PlaybackMode.FOUR_STEMS), base
        )
        assert result.practice_state.playback_mode == PlaybackMode.FOUR_STEMS
        assert result.practice_state.active_result_set_id == rs_id

    def test_stem_mode_without_active_set_rejected(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        base = _current(repo, project_id).revision
        with pytest.raises(PlaybackModeRequiresResultSetError):
            repo.apply_command(project_id, SetPlaybackModeOp(mode=PlaybackMode.BASS_PAIR), base)

        # The rejected command changed nothing.
        assert _current(repo, project_id).revision == base

    def test_original_mode_without_active_set_applies(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        base = _current(repo, project_id).revision
        result = repo.apply_command(
            project_id, SetPlaybackModeOp(mode=PlaybackMode.ORIGINAL), base
        )
        assert result.practice_state.playback_mode == PlaybackMode.ORIGINAL

    def test_undo_stem_mode(
        self, repo: ProjectRepository, separation: SeparationRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        rs_id = _result_set_for(separation, project_id)
        _activate_set(repo, project_id, rs_id)
        project = _current(repo, project_id)
        project = repo.apply_command(
            project_id, SetPlaybackModeOp(mode=PlaybackMode.BASS_PAIR), project.revision
        )
        assert project.practice_state.playback_mode == PlaybackMode.BASS_PAIR

        project = repo.undo(project_id, project.revision)
        assert project.practice_state.playback_mode == PlaybackMode.ORIGINAL


class TestSetMasterGain:
    def test_applies_and_undoes(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        project = _current(repo, project_id)
        assert project.practice_state.master_gain == 1.0

        project = repo.apply_command(
            project_id, SetMasterGainOp(gain=MAX_GAIN), project.revision
        )
        assert project.practice_state.master_gain == MAX_GAIN

        project = repo.undo(project_id, project.revision)
        assert project.practice_state.master_gain == 1.0


class TestSetMonitoringLimiter:
    def test_default_on_and_toggle(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        project = _current(repo, project_id)
        # Spec §10.6.3: the limiter defaults on.
        assert project.practice_state.monitoring_limiter is True

        project = repo.apply_command(
            project_id, SetMonitoringLimiterOp(enabled=False), project.revision
        )
        assert project.practice_state.monitoring_limiter is False

        project = repo.undo(project_id, project.revision)
        assert project.practice_state.monitoring_limiter is True

    def test_persists_across_reopen(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        project = _current(repo, project_id)
        project = repo.apply_command(
            project_id, SetMonitoringLimiterOp(enabled=False), project.revision
        )

        reopened = ProjectRepository(db_path)
        restored = _current(reopened, project_id)
        assert restored.practice_state.monitoring_limiter is False


class TestSetPlaybackSpeed:
    def test_default_is_one_and_applies(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        project = _current(repo, project_id)
        # Spec §11.6: the speed defaults to 1.0.
        assert project.practice_state.playback_speed == 1.0

        project = repo.apply_command(
            project_id, SetPlaybackSpeedOp(speed=MIN_PLAYBACK_SPEED), project.revision
        )
        assert project.practice_state.playback_speed == 0.25
        assert project.can_undo is True

    def test_applies_and_undoes(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        project = _current(repo, project_id)

        project = repo.apply_command(
            project_id, SetPlaybackSpeedOp(speed=MAX_PLAYBACK_SPEED), project.revision
        )
        assert project.practice_state.playback_speed == 2.0

        project = repo.undo(project_id, project.revision)
        assert project.practice_state.playback_speed == 1.0
        assert project.can_redo is True

        project = repo.redo(project_id, project.revision)
        assert project.practice_state.playback_speed == 2.0

    def test_persists_across_reopen(
        self, repo: ProjectRepository, db_path: Path
    ) -> None:
        project_id = _make_ready_project(repo, db_path)
        project = _current(repo, project_id)
        project = repo.apply_command(
            project_id, SetPlaybackSpeedOp(speed=1.5), project.revision
        )

        reopened = ProjectRepository(db_path)
        restored = _current(reopened, project_id)
        assert restored.practice_state.playback_speed == 1.5


def test_track_settings_legacy_json_gains_color_default() -> None:
    # Pre-M2.8 rows have no color key: the pydantic default fills it on
    # load, so no migration is needed (tracks live in the record JSON).
    legacy = TrackSettings(gain=0.5).model_dump()
    del legacy["color"]
    loaded = TrackSettings.model_validate(legacy)
    assert loaded.color == "#8fa3bf"
