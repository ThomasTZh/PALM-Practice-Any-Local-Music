"""Integration tests for the WAV export routes (M2.13, spec §15, §19.2).

Covers ``POST /api/v1/projects/{id}/exports`` validation, idempotency,
and defaults; the ``GET .../exports`` listing; the authenticated
``GET /api/v1/downloads/{artifact_id}`` delivery; and the parameter
resolution that feeds the worker (selection, alignment, availability).
The media worker itself is exercised separately; these tests stop at the
job record and the HTTP surface.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from basseparate.app import _export_parameters_for, create_app
from basseparate.config import AppConfig, resolve_config
from basseparate.domain.asset import AssetRecord, AssetRole, AudioMetadata
from basseparate.domain.confidence import Confidence, ConfidenceKind
from basseparate.domain.export import (
    ExportArtifact,
    ExportFormat,
    ExportNormalization,
)
from basseparate.domain.media_job import JobState, JobType, MediaJob
from basseparate.domain.practice import PracticeState
from basseparate.domain.representation import (
    AudioRepresentation,
    RepresentationProvenance,
    RepresentationRole,
    TimeMapping,
    compute_transform_key,
)
from basseparate.domain.separation import (
    DeviceType,
    ReferenceMixIdentity,
    SeparationMode,
    SeparationResultSet,
    SeparationRun,
    SeparationRunStatus,
    SourceIdentity,
    StemRecord,
    StemRole,
    ValidationStatus,
)
from basseparate.jobs import ParameterResolutionError
from basseparate.storage import (
    ExportArtifactRepository,
    ProjectRepository,
    SeparationRepository,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
HASH = "a" * 64
FRAME_COUNT = 1000
SAMPLE_RATE = 48000
BASE_URL = "http://127.0.0.1:8765"


@pytest.fixture()
def config(tmp_path) -> AppConfig:
    return resolve_config(env={}, cli={"storage_root": str(tmp_path / "store")})


@pytest.fixture()
def app(config: AppConfig):
    return create_app(config)


@pytest.fixture()
def client(app) -> TestClient:
    with TestClient(app, base_url=BASE_URL) as c:
        yield c


@pytest.fixture()
def auth_headers(app) -> dict[str, str]:
    return {"Authorization": f"Bearer {app.state.session_token}"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _payload() -> bytes:
    """A random PCM-sized payload, unique with overwhelming probability."""
    size = FRAME_COUNT * 2 * 4
    filler = uuid.uuid4().bytes
    return (filler * (size // len(filler) + 1))[:size]


def _seed_project(
    app,
    *,
    name: str = "Song",
    ready: bool = True,
    with_active_set: bool = True,
    valid: bool = True,
) -> dict:
    """A project with (optionally a valid) result set and real stem files."""
    projects: ProjectRepository = app.state.repository
    separations: SeparationRepository = app.state.separation_repository
    paths = app.state.storage_paths

    project = projects.create_project(name)
    pcm_id = uuid.uuid4()
    if ready:
        original_hash = _sha(b"original-" + project.id.bytes)
        pcm_bytes = _payload()
        pcm_hash = _sha(pcm_bytes)
        original = AssetRecord(
            id=uuid.uuid4(),
            content_hash=original_hash,
            role=AssetRole.SOURCE_ORIGINAL,
            relative_path=f"data/assets/{original_hash}.orig",
            media_type="audio/wav",
            byte_count=64,
            created_at=NOW,
        )
        pcm = AssetRecord(
            id=pcm_id,
            content_hash=pcm_hash,
            role=AssetRole.SOURCE_PCM,
            relative_path=f"data/assets/{pcm_hash}.pcm",
            media_type="application/octet-stream",
            byte_count=len(pcm_bytes),
            created_at=NOW,
            audio=AudioMetadata(
                sample_rate=SAMPLE_RATE,
                channel_count=2,
                frame_count=FRAME_COUNT,
                sample_format="f32le",
            ),
        )
        representation = AudioRepresentation(
            asset_id=pcm.id,
            parent_asset_id=original.id,
            role=RepresentationRole.CANONICAL,
            sample_rate=SAMPLE_RATE,
            channel_count=2,
            channel_layout="stereo",
            frame_count=FRAME_COUNT,
            content_hash=pcm_hash,
            transform_key=compute_transform_key(original_hash, 0, 1, "ffmpeg 8.1.2"),
            time_mapping=TimeMapping(
                project_rate=SAMPLE_RATE, representation_rate=SAMPLE_RATE
            ),
            provenance=RepresentationProvenance(
                tool="ffmpeg",
                tool_version="ffmpeg 8.1.2",
                profile_version=1,
                created_at=NOW,
            ),
        )
        projects.publish_source(
            project_id=project.id,
            original_asset=original,
            pcm_asset=pcm,
            representation=representation,
            source_stream_index=0,
            sample_rate=SAMPLE_RATE,
            duration_frames=FRAME_COUNT,
            channel_count=2,
            channel_layout="stereo",
            decode_profile_version=1,
            source_metadata={"format": "wav"},
        )
        pcm_path = paths.resolve_asset_path(pcm.relative_path)
        pcm_path.parent.mkdir(parents=True, exist_ok=True)
        pcm_path.write_bytes(pcm_bytes)

    run_id = uuid.uuid4()
    result_set_id = uuid.uuid4()
    run = SeparationRun(
        id=run_id,
        project_id=project.id,
        input_asset_id=pcm_id,
        input_transform_hash=HASH,
        requested_mode=SeparationMode.FOUR_STEMS,
        model_manifest_id=uuid.uuid4(),
        model_manifest_hash=HASH,
        engine_version="demucs-4.1.0",
        adapter_version="adapter-1",
        device_type=DeviceType.CPU,
        status=SeparationRunStatus.COMPLETED,
        result_set_id=result_set_id,
    )
    separations.create_run(run)

    stem_assets: dict[StemRole, uuid.UUID] = {}
    stems: list[StemRecord] = []
    for role, label in ((StemRole.BASS, "Bass"), (StemRole.OTHER, "Other")):
        payload = _payload()
        content_hash = _sha(payload)
        asset = AssetRecord(
            id=uuid.uuid4(),
            content_hash=content_hash,
            role=AssetRole.STEM,
            relative_path=f"data/assets/{content_hash}.pcm",
            media_type="application/octet-stream",
            byte_count=len(payload),
            created_at=NOW,
            audio=AudioMetadata(
                sample_rate=SAMPLE_RATE,
                channel_count=2,
                frame_count=FRAME_COUNT,
                sample_format="f32le",
            ),
        )
        projects.register_asset(asset)
        stem_path = paths.resolve_asset_path(asset.relative_path)
        stem_path.parent.mkdir(parents=True, exist_ok=True)
        stem_path.write_bytes(payload)
        stem_assets[role] = asset.id
        stems.append(
            StemRecord(
                id=uuid.uuid4(),
                result_set_id=result_set_id,
                role=role,
                display_name=label,
                audio_asset_id=asset.id,
                sample_rate=SAMPLE_RATE,
                channel_count=2,
                frame_count=FRAME_COUNT,
                confidence=Confidence(kind=ConfidenceKind.UNAVAILABLE),
            )
        )
    result_set = SeparationResultSet(
        id=result_set_id,
        run_id=run_id,
        project_id=project.id,
        source=SourceIdentity(
            asset_id=pcm_id,
            source_hash=HASH,
            sample_rate=SAMPLE_RATE,
            duration_frames=FRAME_COUNT,
        ),
        output_sample_rate=SAMPLE_RATE,
        output_channel_count=2,
        output_frame_count=FRAME_COUNT,
        available_stem_roles=[StemRole.BASS, StemRole.OTHER],
        stem_ids=[stem.id for stem in stems],
        reference_mix=ReferenceMixIdentity(
            asset_id=uuid.uuid4(), hash=HASH, transformation_hash=HASH
        ),
        validation_status=ValidationStatus.VALID if valid else ValidationStatus.PENDING,
        created_at=NOW,
        cache_key=HASH,
    )
    separations.create_result_set(result_set)
    for stem in stems:
        separations.create_stem(stem)
    if with_active_set:
        projects.set_practice_state(
            project.id,
            PracticeState(active_result_set_id=result_set_id),
        )
    return {
        "project": project,
        "run": run,
        "result_set": result_set,
        "stems": stems,
        "stem_assets": stem_assets,
    }


def _export_job(app, seed: dict, **overrides) -> MediaJob:
    parameters = {
        "result_set_id": str(seed["result_set"].id),
        "asset_ids": [str(seed["stem_assets"][StemRole.BASS])],
        "format": ExportFormat.WAV24.value,
        "target_sample_rate": None,
        "normalize": ExportNormalization.OFF.value,
    }
    parameters.update(overrides)
    return MediaJob(
        id=uuid.uuid4(),
        project_id=seed["project"].id,
        job_type=JobType.EXPORT,
        state=JobState.QUEUED,
        parameters=parameters,
        created_at=NOW,
        updated_at=NOW,
    )


class TestCreateExport:
    def test_defaults_select_all_stems(self, app, client, auth_headers) -> None:
        seed = _seed_project(app)
        resp = client.post(
            f"/api/v1/projects/{seed['project'].id}/exports", json={}, headers=auth_headers
        )
        assert resp.status_code == 201, resp.text
        job = resp.json()
        assert job["job_type"] == "export"
        assert job["state"] in ("queued", "running", "completed", "failed")
        assert job["parameters"]["result_set_id"] == str(seed["result_set"].id)
        assert sorted(job["parameters"]["asset_ids"]) == sorted(
            str(a) for a in seed["stem_assets"].values()
        )
        assert job["parameters"]["format"] == "wav24"
        assert job["parameters"]["target_sample_rate"] is None
        assert job["parameters"]["normalize"] == "off"

    def test_explicit_selection_and_options(self, app, client, auth_headers) -> None:
        seed = _seed_project(app)
        bass_asset = seed["stem_assets"][StemRole.BASS]
        resp = client.post(
            f"/api/v1/projects/{seed['project'].id}/exports",
            json={
                "result_set_id": str(seed["result_set"].id),
                "asset_ids": [str(bass_asset)],
                "format": "wav16",
                "sample_rate": 44100,
                "normalize": "linked_peak",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        parameters = resp.json()["parameters"]
        assert parameters["asset_ids"] == [str(bass_asset)]
        assert parameters["format"] == "wav16"
        assert parameters["target_sample_rate"] == 44100
        assert parameters["normalize"] == "linked_peak"

    def test_unknown_result_set_is_404(self, app, client, auth_headers) -> None:
        seed = _seed_project(app)
        resp = client.post(
            f"/api/v1/projects/{seed['project'].id}/exports",
            json={"result_set_id": str(uuid.uuid4())},
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "RESULT_SET_NOT_FOUND"

    def test_foreign_result_set_is_404(self, app, client, auth_headers) -> None:
        first = _seed_project(app, name="One")
        second = _seed_project(app, name="Two")
        resp = client.post(
            f"/api/v1/projects/{second['project'].id}/exports",
            json={"result_set_id": str(first["result_set"].id)},
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "RESULT_SET_NOT_FOUND"

    def test_selection_outside_set_is_422(self, app, client, auth_headers) -> None:
        seed = _seed_project(app)
        resp = client.post(
            f"/api/v1/projects/{seed['project'].id}/exports",
            json={"asset_ids": [str(uuid.uuid4())]},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "EXPORT_SELECTION"

    def test_no_active_set_is_409(self, app, client, auth_headers) -> None:
        seed = _seed_project(app, with_active_set=False)
        resp = client.post(
            f"/api/v1/projects/{seed['project'].id}/exports", json={}, headers=auth_headers
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "NO_RESULT_SET"

    def test_invalid_set_is_422(self, app, client, auth_headers) -> None:
        seed = _seed_project(app, valid=False)
        resp = client.post(
            f"/api/v1/projects/{seed['project'].id}/exports", json={}, headers=auth_headers
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "EXPORT_SELECTION"

    def test_project_not_ready_is_409(self, app, client, auth_headers) -> None:
        seed = _seed_project(app, ready=False, with_active_set=False)
        resp = client.post(
            f"/api/v1/projects/{seed['project'].id}/exports", json={}, headers=auth_headers
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PROJECT_NOT_READY"

    def test_missing_project_is_404(self, client, auth_headers) -> None:
        resp = client.post(
            f"/api/v1/projects/{uuid.uuid4()}/exports", json={}, headers=auth_headers
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_idempotency_key_replays_response(self, app, client, auth_headers) -> None:
        seed = _seed_project(app)
        headers = {**auth_headers, "Idempotency-Key": "export-1"}
        first = client.post(
            f"/api/v1/projects/{seed['project'].id}/exports", json={}, headers=headers
        )
        second = client.post(
            f"/api/v1/projects/{seed['project'].id}/exports", json={}, headers=headers
        )
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] == second.json()["id"]

    def test_idempotency_conflict_is_409(self, app, client, auth_headers) -> None:
        seed = _seed_project(app)
        headers = {**auth_headers, "Idempotency-Key": "export-2"}
        client.post(
            f"/api/v1/projects/{seed['project'].id}/exports", json={}, headers=headers
        )
        conflict = client.post(
            f"/api/v1/projects/{seed['project'].id}/exports",
            json={"format": "wav16"},
            headers=headers,
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    def test_requires_auth(self, app, client) -> None:
        seed = _seed_project(app)
        resp = client.post(f"/api/v1/projects/{seed['project'].id}/exports", json={})
        assert resp.status_code == 401


class TestExportListing:
    def test_empty_listing(self, app, client, auth_headers) -> None:
        seed = _seed_project(app)
        resp = client.get(
            f"/api/v1/projects/{seed['project'].id}/exports", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json() == {"artifacts": []}

    def test_listing_reports_artifacts_and_download_url(
        self, app, client, auth_headers
    ) -> None:
        seed = _seed_project(app)
        exports: ExportArtifactRepository = app.state.export_repository
        jobs = app.state.job_repository
        job = jobs.create_job(
            seed["project"].id,
            JobType.EXPORT,
            parameters={"result_set_id": str(seed["result_set"].id), "asset_ids": []},
        )
        digest = _sha(b"RIFF" + b"\x11" * 120)
        artifact = ExportArtifact(
            id=uuid.uuid4(),
            job_id=job.id,
            project_id=seed["project"].id,
            result_set_id=seed["result_set"].id,
            stem_id=seed["stems"][0].id,
            audio_asset_id=seed["stem_assets"][StemRole.BASS],
            role=StemRole.BASS,
            format=ExportFormat.WAV24,
            sample_rate=48000,
            channel_count=2,
            frame_count=FRAME_COUNT,
            normalized=True,
            gain_db=-1.0,
            dither="triangular",
            sha256=digest,
            byte_size=124,
            relative_path=f"data/exports/{digest}.wav",
            download_filename="Bass-123456-48k-24bit.wav",
            created_at=NOW,
        )
        exports.publish_artifacts(job.id, [artifact])

        resp = client.get(
            f"/api/v1/projects/{seed['project'].id}/exports", headers=auth_headers
        )
        assert resp.status_code == 200
        artifacts = resp.json()["artifacts"]
        assert len(artifacts) == 1
        item = artifacts[0]
        assert item["artifact_id"] == str(artifact.id)
        assert item["job_state"] == "queued"
        assert item["role"] == "bass"
        assert item["format"] == "wav24"
        assert item["normalized"] is True
        assert item["gain_db"] == -1.0
        assert item["dither"] == "triangular"
        assert item["download_url"] == f"/api/v1/downloads/{artifact.id}"


class TestDownloadRoute:
    def _publish_artifact(self, app, seed) -> tuple[ExportArtifact, bytes]:
        payload = b"RIFF" + b"\x11" * 120
        digest = _sha(payload)
        paths = app.state.storage_paths
        destination = paths.data / "exports" / f"{digest}.wav"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        jobs = app.state.job_repository
        job = jobs.create_job(
            seed["project"].id,
            JobType.EXPORT,
            parameters={"result_set_id": str(seed["result_set"].id), "asset_ids": []},
        )
        artifact = ExportArtifact(
            id=uuid.uuid4(),
            job_id=job.id,
            project_id=seed["project"].id,
            result_set_id=seed["result_set"].id,
            stem_id=seed["stems"][0].id,
            audio_asset_id=seed["stem_assets"][StemRole.BASS],
            role=StemRole.BASS,
            format=ExportFormat.WAV24,
            sample_rate=48000,
            channel_count=2,
            frame_count=FRAME_COUNT,
            normalized=False,
            gain_db=None,
            dither="triangular",
            sha256=digest,
            byte_size=len(payload),
            relative_path=f"data/exports/{digest}.wav",
            download_filename="Bass-123456-48k-24bit.wav",
            created_at=NOW,
        )
        app.state.export_repository.publish_artifacts(job.id, [artifact])
        return artifact, payload

    def test_download_delivers_bytes_and_headers(self, app, client, auth_headers) -> None:
        seed = _seed_project(app)
        artifact, payload = self._publish_artifact(app, seed)
        resp = client.get(f"/api/v1/downloads/{artifact.id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.content == payload
        assert resp.headers["content-type"] == "audio/wav"
        assert resp.headers["content-length"] == str(len(payload))
        disposition = resp.headers["content-disposition"]
        assert disposition.startswith("attachment;")
        assert 'filename="Bass-123456-48k-24bit.wav"' in disposition
        assert "filename*=UTF-8''Bass-123456-48k-24bit.wav" in disposition
        assert resp.headers["x-content-sha256"] == artifact.sha256

    def test_unknown_artifact_is_404(self, app, client, auth_headers) -> None:
        resp = client.get(f"/api/v1/downloads/{uuid.uuid4()}", headers=auth_headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "EXPORT_ARTIFACT_NOT_FOUND"

    def test_missing_file_is_404(self, app, client, auth_headers) -> None:
        seed = _seed_project(app)
        artifact, _payload = self._publish_artifact(app, seed)
        paths = app.state.storage_paths
        paths.resolve_asset_path(artifact.relative_path).unlink()
        resp = client.get(f"/api/v1/downloads/{artifact.id}", headers=auth_headers)
        assert resp.status_code == 404
        assert "missing from storage" in resp.json()["error"]["message"]

    def test_download_requires_auth(self, app, client) -> None:
        seed = _seed_project(app)
        artifact, _payload = self._publish_artifact(app, seed)
        resp = client.get(f"/api/v1/downloads/{artifact.id}")
        assert resp.status_code == 401


class TestExportParameterResolution:
    def _resolve(self, app, seed, **overrides) -> dict:
        job = _export_job(app, seed, **overrides)
        return _export_parameters_for(
            job,
            app.state.repository,
            app.state.separation_repository,
            app.state.storage_paths,
        )

    def test_happy_path_selected_stem(self, app, client) -> None:
        seed = _seed_project(app)
        parameters = self._resolve(app, seed)
        assert parameters["result_set_id"] == str(seed["result_set"].id)
        assert parameters["format"] == "wav24"
        assert parameters["target_sample_rate"] is None
        assert parameters["source_sample_rate"] == SAMPLE_RATE
        assert len(parameters["stems"]) == 1
        stem = parameters["stems"][0]
        assert stem["role"] == "bass"
        assert stem["asset_id"] == str(seed["stem_assets"][StemRole.BASS])
        assert stem["frame_count"] == FRAME_COUNT
        assert Path(stem["source_path"]).is_file()
        assert stem["download_filename"] == (
            f"Bass-{seed['result_set'].id.hex[:6]}-48k-24bit.wav"
        )

    def test_all_stems_with_resampled_rate(self, app, client) -> None:
        seed = _seed_project(app)
        parameters = self._resolve(
            app,
            seed,
            asset_ids=None,
            target_sample_rate=44100,
            format="wav32f",
        )
        prefix = seed["result_set"].id.hex[:6]
        assert len(parameters["stems"]) == 2
        names = {stem["download_filename"] for stem in parameters["stems"]}
        assert names == {f"Bass-{prefix}-44.1k-float32.wav", f"Other-{prefix}-44.1k-float32.wav"}

    def test_misaligned_stems_are_rejected(self, app, client) -> None:
        seed = _seed_project(app)
        separations = app.state.separation_repository
        # Rewrite one stem with a different frame count.
        bad = StemRecord(
            id=seed["stems"][1].id,
            result_set_id=seed["result_set"].id,
            role=seed["stems"][1].role,
            display_name=seed["stems"][1].display_name,
            audio_asset_id=seed["stems"][1].audio_asset_id,
            sample_rate=SAMPLE_RATE,
            channel_count=2,
            frame_count=FRAME_COUNT - 10,
            confidence=seed["stems"][1].confidence,
        )
        conn = separations._db_path  # noqa: SLF001 - test rewrites the stored row
        import sqlite3

        with sqlite3.connect(str(conn)) as raw:
            raw.execute(
                "UPDATE stems SET record_json = ? WHERE id = ?",
                (bad.model_dump_json(), str(bad.id)),
            )
            raw.commit()
        with pytest.raises(ParameterResolutionError) as excinfo:
            self._resolve(app, seed, asset_ids=None)
        assert excinfo.value.code == "EXPORT_ALIGNMENT"

    def test_missing_stem_file_is_rejected(self, app, client) -> None:
        seed = _seed_project(app)
        projects = app.state.repository
        asset = projects.get_asset(seed["stem_assets"][StemRole.BASS])
        assert asset is not None
        app.state.storage_paths.resolve_asset_path(asset.relative_path).unlink()
        with pytest.raises(ParameterResolutionError) as excinfo:
            self._resolve(app, seed)
        assert excinfo.value.code == "EXPORT_STEM_MISSING"

    def test_unknown_asset_in_selection_is_rejected(self, app, client) -> None:
        seed = _seed_project(app)
        with pytest.raises(ParameterResolutionError) as excinfo:
            self._resolve(app, seed, asset_ids=[str(uuid.uuid4())])
        assert excinfo.value.code == "EXPORT_SELECTION"

    def test_bad_options_are_rejected(self, app, client) -> None:
        seed = _seed_project(app)
        with pytest.raises(ParameterResolutionError) as excinfo:
            self._resolve(app, seed, format="wav64")
        assert excinfo.value.code == "EXPORT_OPTIONS"
        with pytest.raises(ParameterResolutionError) as excinfo:
            self._resolve(app, seed, target_sample_rate=32000)
        assert excinfo.value.code == "EXPORT_OPTIONS"
        with pytest.raises(ParameterResolutionError) as excinfo:
            self._resolve(app, seed, normalize="per_stem")
        assert excinfo.value.code == "EXPORT_OPTIONS"

    def test_invalid_result_set_is_rejected(self, app, client) -> None:
        seed = _seed_project(app)
        with pytest.raises(ParameterResolutionError) as excinfo:
            self._resolve(app, seed, result_set_id=str(uuid.uuid4()))
        assert excinfo.value.code == "EXPORT_RESULT_SET"

    def test_job_type_mismatch_returns_empty(self, app, client) -> None:
        seed = _seed_project(app)
        job = MediaJob(
            id=uuid.uuid4(),
            project_id=seed["project"].id,
            job_type=JobType.PROBE,
            state=JobState.QUEUED,
            created_at=NOW,
            updated_at=NOW,
        )
        assert (
            _export_parameters_for(
                job,
                app.state.repository,
                app.state.separation_repository,
                app.state.storage_paths,
            )
            == {}
        )
