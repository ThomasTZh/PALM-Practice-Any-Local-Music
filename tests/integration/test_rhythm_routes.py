"""Read-only rhythm-grid endpoint (M3.11/M3.17)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from basseparate.app import create_app
from basseparate.config import AppConfig, resolve_config
from basseparate.domain.confidence import Confidence, ConfidenceKind
from basseparate.domain.rhythm import (
    ZERO_MUSICAL_POSITION,
    BarOriginState,
    GridValidity,
    MeterRegion,
    MeterTempoUnit,
    MusicalPosition,
    ProjectRhythmState,
    PulseAcceptance,
    PulseRole,
    RhythmBranchRecord,
    RhythmDisplayMode,
    RhythmOrigin,
    RhythmPulse,
    TempoAnchor,
)
from basseparate.storage import ProjectRepository, RhythmRepository

NOW = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
BASE_URL = "http://127.0.0.1:8765"


@pytest.fixture()
def config(tmp_path: Path) -> AppConfig:
    return resolve_config(env={}, cli={"storage_root": str(tmp_path / "store")})


@pytest.fixture()
def app(config: AppConfig):
    return create_app(config)


@pytest.fixture()
def client(app):
    with TestClient(app, base_url=BASE_URL) as c:
        yield c


@pytest.fixture()
def headers(app) -> dict[str, str]:
    return {"Authorization": f"Bearer {app.state.session_token}"}


def _seed(app, *, with_branch: bool = True) -> uuid.UUID:
    projects = ProjectRepository(app.state.repository._db_path)
    project = projects.create_project("Grid")
    db = app.state.repository._db_path
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            """
            UPDATE projects SET
                status = 'ready', source_asset_id = ?, canonical_asset_id = ?,
                source_stream_index = 0, sample_rate = 48000,
                duration_frames = 300000, source_channel_count = 2,
                source_channel_layout = 'stereo', decode_profile_version = 1
            WHERE id = ?
            """,
            (str(uuid.uuid4()), str(uuid.uuid4()), str(project.id)),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()
    if not with_branch:
        return project.id
    branch_id = uuid.uuid4()
    confidence = Confidence(kind=ConfidenceKind.HEURISTIC, value=0.9)
    sources = [(0, 0), (48_000, 2), (96_000, 4)]
    anchor_ids = [uuid.uuid4() for _ in sources]
    pulse_ids = [uuid.uuid4() for _ in sources]
    anchors = [
        TempoAnchor(
            id=anchor_ids[index],
            branch_id=branch_id,
            source_frame=source,
            musical_position=MusicalPosition(numerator=musical, denominator=1),
            origin=RhythmOrigin.MANUAL,
            pulse_id=pulse_ids[index],
            confidence=confidence,
            created_at=NOW,
            updated_at=NOW,
        )
        for index, (source, musical) in enumerate(sources)
    ]
    pulses = [
        RhythmPulse(
            id=pulse_ids[index],
            parent_id=branch_id,
            source_frame=source,
            model_frame_index=index,
            role=PulseRole.DOWNBEAT if index == 0 else PulseRole.BEAT,
            acceptance=PulseAcceptance.ACCEPTED,
            confidence=confidence,
            origin=RhythmOrigin.AUTOMATIC,
            tempo_anchor_id=anchor_ids[index],
        )
        for index, (source, _musical) in enumerate(sources)
    ]
    region = MeterRegion(
        id=uuid.uuid4(),
        branch_id=branch_id,
        start=MusicalPosition(numerator=0, denominator=1),
        numerator=4,
        denominator=4,
        grouping=[1, 1, 1, 1],
        display_tempo_unit=MeterTempoUnit.QUARTER,
        origin=RhythmOrigin.MANUAL,
    )
    Branch = RhythmBranchRecord(
        id=branch_id,
        project_id=project.id,
        revision=3,
        source_duration_frames=300_000,
        pulses=pulses,
        tempo_anchors=anchors,
        meter_regions=[region],
        bar_origin=BarOriginState(first_numbered_bar_position=ZERO_MUSICAL_POSITION),
        grid_validity=GridValidity.VALID,
        created_at=NOW,
        updated_at=NOW,
    )
    RhythmRepository(db).create_branch(Branch)
    projects.set_rhythm_state(
        project.id,
        ProjectRhythmState(
            active_branch_id=branch_id,
            display_mode=RhythmDisplayMode.EDITED,
        ),
    )
    return project.id


def test_returns_grid_and_branch_metadata(client: TestClient, app, headers) -> None:
    project_id = _seed(app)
    response = client.get(
        f"/api/v1/projects/{project_id}/rhythm-grid",
        params={"start_frame": 0, "end_frame": 96_000, "detail": "primary"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["branch_revision"] == 3
    assert data["source_sample_rate"] == 48_000
    assert data["branch_validity"] == "valid"
    labels = [event["label"] for event in data["grid"]["events"]]
    assert labels[:5] == ["1", "1.1", "1.2", "1.3", "1.4"]
    assert data["grid"]["gaps"] == []
    assert len(data["pulses"]) == 3


def test_unavailable_without_active_branch(client: TestClient, app, headers) -> None:
    project_id = _seed(app, with_branch=False)
    response = client.get(f"/api/v1/projects/{project_id}/rhythm-grid", headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RHYTHM_GRID_UNAVAILABLE"


def test_invalid_range_is_422(client: TestClient, app, headers) -> None:
    project_id = _seed(app)
    response = client.get(
        f"/api/v1/projects/{project_id}/rhythm-grid",
        params={"start_frame": 400_000},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "RHYTHM_GRID_RANGE_INVALID"


def test_snap_endpoint_uses_visual_radius(client: TestClient, app, headers) -> None:
    project_id = _seed(app)
    response = client.post(
        f"/api/v1/projects/{project_id}/rhythm-snap",
        json={
            "position_frames": 23_500,
            "mode": "beat",
            "frames_per_pixel": 100.0,
            "radius_css_px": 8,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["snapped"] is True
    assert data["snapped_frame"] == 24_000
    assert data["target_kind"] == "primary"


def test_snap_endpoint_rejects_out_of_range(client: TestClient, app, headers) -> None:
    project_id = _seed(app)
    response = client.post(
        f"/api/v1/projects/{project_id}/rhythm-snap",
        json={
            "position_frames": 400_000,
            "mode": "bar",
            "frames_per_pixel": 100.0,
        },
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "RHYTHM_SNAP_INVALID"


def test_add_musical_loop_command(client: TestClient, app, headers) -> None:
    project_id = _seed(app)
    project = app.state.repository.get_project(project_id)
    assert project is not None
    response = client.post(
        f"/api/v1/projects/{project_id}/commands",
        json={
            "command_id": str(uuid.uuid4()),
            "idempotency_key": uuid.uuid4().hex,
            "base_revision": project.revision,
            "op": {
                "type": "add_musical_loop",
                "start_musical": {"numerator": 0, "denominator": 1},
                "end_musical": {"numerator": 2, "denominator": 1},
                "name": "Musical",
            },
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    loops = response.json()["practice_state"]["loops"]
    loop = next(loop for loop in loops if loop["name"] == "Musical")
    assert loop["anchor_mode"] == "musical"
    assert loop["start_frames"] == 0
    assert loop["end_frames"] == 48_000


def test_musical_loop_conversion_endpoint(client: TestClient, app, headers) -> None:
    project_id = _seed(app)
    project = app.state.repository.get_project(project_id)
    assert project is not None
    added = client.post(
        f"/api/v1/projects/{project_id}/commands",
        json={
            "command_id": str(uuid.uuid4()),
            "idempotency_key": uuid.uuid4().hex,
            "base_revision": project.revision,
            "op": {
                "type": "add_musical_loop",
                "start_musical": {"numerator": 0, "denominator": 1},
                "end_musical": {"numerator": 2, "denominator": 1},
            },
        },
        headers=headers,
    )
    assert added.status_code == 200, added.text
    loop = added.json()["practice_state"]["loops"][0]
    converted = client.post(
        f"/api/v1/projects/{project_id}/commands",
        json={
            "command_id": str(uuid.uuid4()),
            "idempotency_key": uuid.uuid4().hex,
            "base_revision": added.json()["revision"],
            "op": {
                "type": "convert_loop",
                "loop_id": loop["id"],
                "target": "source",
            },
        },
        headers=headers,
    )
    assert converted.status_code == 200, converted.text
    assert converted.json()["practice_state"]["loops"][0]["anchor_mode"] == "source"
