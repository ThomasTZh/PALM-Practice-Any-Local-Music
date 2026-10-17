"""Repository tests for durable media jobs (M1.4)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from basseparate.domain.media_job import (
    InvalidJobTransition,
    JobStage,
    JobState,
    JobType,
)
from basseparate.storage.db import initialize_database
from basseparate.storage.repository import ImportRepository, JobRepository, ProjectRepository


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "basseparate.db"
    initialize_database(path)
    return path


@pytest.fixture()
def projects(db_path: Path) -> ProjectRepository:
    return ProjectRepository(db_path)


@pytest.fixture()
def imports(db_path: Path) -> ImportRepository:
    return ImportRepository(db_path)


@pytest.fixture()
def jobs(db_path: Path) -> JobRepository:
    return JobRepository(db_path)


def _job_id(projects: ProjectRepository, jobs: JobRepository) -> uuid.UUID:
    project = projects.create_project("jobs")
    record = jobs.create_job(project.id, JobType.PROBE)
    return record.id


class TestCreateAndGet:
    def test_create_defaults(self, projects: ProjectRepository, jobs: JobRepository) -> None:
        project = projects.create_project("jobs")
        record = jobs.create_job(project.id, JobType.PROBE)
        assert record.state is JobState.QUEUED
        assert record.project_id == project.id
        assert record.import_id is None
        assert record.job_type is JobType.PROBE
        assert record.max_threads == 4

    def test_create_with_import_and_threads(
        self,
        projects: ProjectRepository,
        imports: ImportRepository,
        jobs: JobRepository,
    ) -> None:
        project = projects.create_project("jobs")
        import_record = imports.create_import(project.id, "a.wav", 10)
        record = jobs.create_job(
            project.id, JobType.WAVEFORM, import_id=import_record.id, max_threads=2
        )
        assert record.import_id == import_record.id
        assert record.max_threads == 2

    def test_get_missing_returns_none(self, jobs: JobRepository) -> None:
        assert jobs.get_job(uuid.uuid4()) is None

    def test_create_rejects_unknown_project(self, jobs: JobRepository) -> None:
        from basseparate.storage import DatabaseError

        with pytest.raises(DatabaseError):
            jobs.create_job(uuid.uuid4(), JobType.PROBE)


class TestList:
    def test_list_for_project(self, projects: ProjectRepository, jobs: JobRepository) -> None:
        project = projects.create_project("mine")
        other = projects.create_project("theirs")
        a = jobs.create_job(project.id, JobType.PROBE)
        b = jobs.create_job(project.id, JobType.WAVEFORM)
        jobs.create_job(other.id, JobType.PROBE)

        listed = jobs.list_jobs_for_project(project.id)
        assert [j.id for j in listed] == [a.id, b.id]

    def test_list_by_state(self, projects: ProjectRepository, jobs: JobRepository) -> None:
        project = projects.create_project("mine")
        a = jobs.create_job(project.id, JobType.PROBE)
        b = jobs.create_job(project.id, JobType.PROBE)
        jobs.set_state(a.id, JobState.RUNNING)

        running = jobs.list_jobs_by_state(JobState.RUNNING)
        queued = jobs.list_jobs_by_state(JobState.QUEUED)
        assert [j.id for j in running] == [a.id]
        assert [j.id for j in queued] == [b.id]


class TestTransitions:
    def test_valid_lifecycle(self, projects: ProjectRepository, jobs: JobRepository) -> None:
        job_id = _job_id(projects, jobs)
        assert jobs.set_state(job_id, JobState.RUNNING).state is JobState.RUNNING
        assert jobs.set_state(job_id, JobState.CANCELLING).state is JobState.CANCELLING
        assert jobs.set_state(job_id, JobState.CANCELLED).state is JobState.CANCELLED

    def test_invalid_transition_raises(
        self, projects: ProjectRepository, jobs: JobRepository
    ) -> None:
        job_id = _job_id(projects, jobs)
        with pytest.raises(InvalidJobTransition):
            jobs.set_state(job_id, JobState.COMPLETED)  # queued → completed is not allowed

    def test_terminal_state_is_sticky(
        self, projects: ProjectRepository, jobs: JobRepository
    ) -> None:
        job_id = _job_id(projects, jobs)
        jobs.set_state(job_id, JobState.RUNNING)
        jobs.fail_job(job_id, "TEST", "boom")
        with pytest.raises(InvalidJobTransition):
            jobs.set_state(job_id, JobState.RUNNING)

    def test_interrupted_can_resume(self, projects: ProjectRepository, jobs: JobRepository) -> None:
        job_id = _job_id(projects, jobs)
        jobs.set_state(job_id, JobState.RUNNING)
        jobs.set_state(job_id, JobState.INTERRUPTED)
        assert jobs.set_state(job_id, JobState.QUEUED).state is JobState.QUEUED

    def test_set_state_missing_job(self, jobs: JobRepository) -> None:
        from basseparate.storage import DatabaseError

        with pytest.raises(DatabaseError):
            jobs.set_state(uuid.uuid4(), JobState.RUNNING)


class TestProgressAndResult:
    def test_set_progress(self, projects: ProjectRepository, jobs: JobRepository) -> None:
        job_id = _job_id(projects, jobs)
        jobs.set_state(job_id, JobState.RUNNING)
        record = jobs.set_progress(job_id, JobStage.DECODING, fraction=0.25, detail="1s / 4s")
        assert record.stage is JobStage.DECODING
        assert record.progress_fraction == 0.25
        assert record.progress_detail == "1s / 4s"

    def test_set_progress_partial(self, projects: ProjectRepository, jobs: JobRepository) -> None:
        job_id = _job_id(projects, jobs)
        jobs.set_state(job_id, JobState.RUNNING)
        record = jobs.set_progress(job_id, JobStage.INSPECTING)
        assert record.stage is JobStage.INSPECTING
        assert record.progress_fraction is None

    def test_complete_job(self, projects: ProjectRepository, jobs: JobRepository) -> None:
        job_id = _job_id(projects, jobs)
        jobs.set_state(job_id, JobState.RUNNING)
        result = {"format_name": "wav", "byte_count": 123}
        record = jobs.complete_job(job_id, result)
        assert record.state is JobState.COMPLETED
        assert record.stage is JobStage.READY
        assert record.progress_fraction == 1.0
        assert record.result == result

    def test_complete_requires_running(
        self, projects: ProjectRepository, jobs: JobRepository
    ) -> None:
        job_id = _job_id(projects, jobs)
        with pytest.raises(InvalidJobTransition):
            jobs.complete_job(job_id, {})

    def test_fail_job(self, projects: ProjectRepository, jobs: JobRepository) -> None:
        job_id = _job_id(projects, jobs)
        jobs.set_state(job_id, JobState.RUNNING)
        record = jobs.fail_job(job_id, "PROBE_TIMEOUT", "took too long")
        assert record.state is JobState.FAILED
        assert record.error_code == "PROBE_TIMEOUT"
        assert record.error == "took too long"

    def test_error_message_truncated(
        self, projects: ProjectRepository, jobs: JobRepository
    ) -> None:
        job_id = _job_id(projects, jobs)
        jobs.set_state(job_id, JobState.RUNNING)
        record = jobs.fail_job(job_id, "E", "x" * 5000)
        assert len(record.error) == 2000


class TestMarkInterrupted:
    def test_flips_running_and_cancelling(
        self, projects: ProjectRepository, jobs: JobRepository
    ) -> None:
        project = projects.create_project("mine")
        a = jobs.create_job(project.id, JobType.PROBE)
        b = jobs.create_job(project.id, JobType.PROBE)
        c = jobs.create_job(project.id, JobType.PROBE)
        jobs.set_state(a.id, JobState.RUNNING)
        jobs.set_state(b.id, JobState.RUNNING)
        jobs.set_state(b.id, JobState.CANCELLING)
        # c stays queued

        count = jobs.mark_interrupted()
        assert count == 2
        assert jobs.get_job(a.id).state is JobState.INTERRUPTED
        assert jobs.get_job(b.id).state is JobState.INTERRUPTED
        assert jobs.get_job(c.id).state is JobState.QUEUED

    def test_no_running_jobs(self, projects: ProjectRepository, jobs: JobRepository) -> None:
        assert jobs.mark_interrupted() == 0


class TestForeignKeys:
    def test_project_delete_cascades(
        self, projects: ProjectRepository, jobs: JobRepository
    ) -> None:
        project = projects.create_project("mine")
        job = jobs.create_job(project.id, JobType.PROBE)
        # Delete the project row directly (the API blocks deleting non-empty
        # projects, but the FK behavior is what is under test here).
        import sqlite3

        conn = sqlite3.connect(str(jobs._db_path))  # noqa: SLF001
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM projects WHERE id = ?", (str(project.id),))
        conn.execute("COMMIT")
        conn.close()
        assert jobs.get_job(job.id) is None

    def test_import_delete_sets_null(
        self,
        projects: ProjectRepository,
        imports: ImportRepository,
        jobs: JobRepository,
    ) -> None:
        project = projects.create_project("mine")
        import_record = imports.create_import(project.id, "a.wav", 10)
        job = jobs.create_job(project.id, JobType.PROBE, import_id=import_record.id)

        import sqlite3

        conn = sqlite3.connect(str(jobs._db_path))  # noqa: SLF001
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM imports WHERE id = ?", (str(import_record.id),))
        conn.execute("COMMIT")
        conn.close()
        reloaded = jobs.get_job(job.id)
        assert reloaded is not None
        assert reloaded.import_id is None


class TestInFlightExportAssetIds:
    """M2.13 §9.5.6: the reclaim pin hook reads in-flight export jobs."""

    def _export_job(
        self,
        projects: ProjectRepository,
        jobs: JobRepository,
        asset_ids: list[str],
    ):
        project = projects.create_project("pin")
        return jobs.create_job(
            project.id,
            JobType.EXPORT,
            parameters={"result_set_id": str(uuid.uuid4()), "asset_ids": asset_ids},
        )

    def test_pins_assets_of_non_terminal_export_jobs(
        self,
        projects: ProjectRepository,
        jobs: JobRepository,
    ) -> None:
        a, b, c, d = (str(uuid.uuid4()) for _ in range(4))
        self._export_job(projects, jobs, [a, b])  # stays queued
        running = self._export_job(projects, jobs, [b])
        jobs.set_state(running.id, JobState.RUNNING)
        completed = self._export_job(projects, jobs, [c])
        jobs.set_state(completed.id, JobState.RUNNING)
        jobs.set_state(completed.id, JobState.COMPLETED)
        failed = self._export_job(projects, jobs, [d])
        jobs.fail_job(failed.id, "TEST", "done")

        assert jobs.in_flight_export_asset_ids() == {uuid.UUID(a), uuid.UUID(b)}

    def test_ignores_other_job_types_and_malformed_parameters(
        self,
        projects: ProjectRepository,
        jobs: JobRepository,
    ) -> None:
        a = str(uuid.uuid4())
        jobs.create_job(
            projects.create_project("wf").id,
            JobType.WAVEFORM,
            parameters={"asset_ids": [a], "source_path": "/x"},
        )
        # A malformed parameters blob must not break the scan.
        job = self._export_job(projects, jobs, ["not-a-uuid"])
        import sqlite3

        conn = sqlite3.connect(str(jobs._db_path))  # noqa: SLF001
        conn.execute(
            "UPDATE media_jobs SET parameters = 'not json' WHERE id = ?",
            (str(job.id),),
        )
        conn.commit()
        conn.close()

        assert jobs.in_flight_export_asset_ids() == set()
