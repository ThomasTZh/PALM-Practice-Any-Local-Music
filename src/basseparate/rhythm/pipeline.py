"""Analyze Rhythm run graph (M3.17 §19.1-§19.3).

One durable rhythm analysis run executes the default pipeline:

    prepared input -> Beat This! activations -> pulse decoding
    -> tempo map -> meter inference -> editable rhythm branch

The run row (``rhythm_analysis_runs``) is the durable identity; a worker
thread executes the stages so the HTTP request returns immediately. A
restart marks an executing run interrupted (M3.18 §20.7) and leaves
completed artifacts reusable.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from basseparate.domain.asset import AssetRecord
from basseparate.domain.meter import ManualMeterRegion, build_meter_map
from basseparate.domain.project import ProjectRecord
from basseparate.domain.rhythm import (
    BarOriginState,
    RhythmAnalysisRun,
    RhythmAnalysisStatus,
    RhythmDisplayMode,
)
from basseparate.domain.rhythm_input import RhythmInputPlan
from basseparate.media.rhythm_input import prepare_rhythm_input
from basseparate.models.install import ModelStore
from basseparate.models.rhythm_registry import (
    BEAT_THIS_FINAL0_ID,
    RhythmModelManifest,
    get_rhythm_model,
    rhythm_manifest_hash,
)
from basseparate.rhythm.activations import (
    ActivationRequest,
    RhythmActivationStore,
    run_and_publish,
)
from basseparate.rhythm.decoder import decode_artifact
from basseparate.rhythm.grid import default_bar_origin
from basseparate.rhythm.meter import (
    MeterFeatureStore,
    extract_meter_features,
    infer_meter,
)
from basseparate.rhythm.results import (
    activate_branch,
    create_branch_from_result,
    publish_decoded_result,
)
from basseparate.rhythm.tempo import (
    build_automatic_tempo_map,
    map_round_trip_error_frames,
)
from basseparate.storage.paths import StoragePaths
from basseparate.storage.repository import ProjectRepository, RhythmRepository


class RhythmPipelineError(Exception):
    """A pipeline precondition failed before any stage started."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def automatic_bar_origin(meter_map: object | None) -> BarOriginState:
    """Number the first bar at the first meter region (M3.20 correction).

    The automatic meter selection can start after musical zero. Using
    zero as the bar origin then fails the grid/metronome boundary check.
    """
    from basseparate.domain.meter import MeterMap

    if isinstance(meter_map, MeterMap) and meter_map.regions:
        return BarOriginState(first_numbered_bar_position=meter_map.regions[0].start)
    return default_bar_origin()


@dataclass(frozen=True)
class RhythmRunRequest:
    """Inputs of one Analyze Rhythm request (§19.3)."""

    model_id: str = BEAT_THIS_FINAL0_ID
    device: str = "cpu"
    force_rerun: bool = False
    threads: int = 4


class RhythmPipelineService:
    """Start and execute durable rhythm analysis runs."""

    def __init__(
        self,
        *,
        paths: StoragePaths,
        projects: ProjectRepository,
        rhythm: RhythmRepository,
        model_store: ModelStore | None = None,
        worker_command: list[str] | None = None,
    ) -> None:
        self._paths = paths
        self._projects = projects
        self._rhythm = rhythm
        self._models = model_store or ModelStore(paths.data / "models")
        self._worker_command = worker_command

    # -- request validation -------------------------------------------------
    def manifest(self, model_id: str) -> RhythmModelManifest:
        try:
            manifest = get_rhythm_model(model_id)
        except Exception as exc:  # noqa: BLE001 - registry error -> request error
            raise RhythmPipelineError("RHYTHM_MODEL_UNKNOWN", str(exc)) from exc
        if not self._models.is_installed(manifest, verify_hash=False):
            raise RhythmPipelineError(
                "RHYTHM_MODEL_NOT_INSTALLED",
                f"{manifest.model_id} is not installed; install it explicitly first",
            )
        return manifest

    def _source(self, project: ProjectRecord) -> tuple[AssetRecord, Path]:
        if project.canonical_asset_id is None or project.sample_rate is None:
            raise RhythmPipelineError(
                "PROJECT_NOT_READY",
                "the project needs canonical audio before rhythm analysis",
            )
        asset = self._projects.get_asset(project.canonical_asset_id)
        if asset is None:
            raise RhythmPipelineError("PROJECT_NOT_READY", "canonical asset is missing")
        path = self._paths.resolve_asset_path(asset.relative_path)
        if not path.is_file():
            raise RhythmPipelineError(
                "PROJECT_NOT_READY", "the canonical asset file is missing"
            )
        return asset, path

    def _input_plan(
        self,
        project: ProjectRecord,
        asset: AssetRecord,
        manifest: RhythmModelManifest,
        manifest_hash: str,
    ) -> RhythmInputPlan:
        audio = asset.audio
        if audio is None or project.sample_rate is None:
            raise RhythmPipelineError("PROJECT_NOT_READY", "canonical audio metadata is missing")
        channels = audio.channel_count
        downmix = None
        if channels > 2:
            if channels != 6:
                raise RhythmPipelineError(
                    "RHYTHM_INPUT_UNSUPPORTED",
                    "multichannel rhythm input currently requires 5.1 or stereo",
                )
            from basseparate.domain.preparation import DownmixSpec

            downmix = DownmixSpec(mode="standard_5_1")
        return RhythmInputPlan(
            input_role="original_mix",
            asset_id=asset.id,
            source_hash=asset.content_hash,
            sample_rate=audio.sample_rate,
            channel_count=channels,
            downmix=downmix,
            model_id=manifest.model_id,
            model_manifest_hash=manifest_hash,
            adapter_version=manifest.adapter_version,
        )

    def start(self, project_id: uuid.UUID, request: RhythmRunRequest) -> RhythmAnalysisRun:
        """Validate the request, persist a durable run row, and start execution."""
        project = self._projects.get_project(project_id)
        if project is None:
            raise RhythmPipelineError("PROJECT_NOT_FOUND", "unknown project")
        manifest = self.manifest(request.model_id)
        asset, _path = self._source(project)
        manifest_hash = rhythm_manifest_hash(manifest)
        plan = self._input_plan(project, asset, manifest, manifest_hash)

        if not request.force_rerun:
            for previous in self._rhythm.list_runs_for_project(project_id):
                if (
                    previous.status is RhythmAnalysisStatus.COMPLETED
                    and previous.input_hash == plan.source_hash
                    and previous.model_manifest_id == manifest.model_id
                    and previous.model_preset == manifest.preset
                ):
                    return previous

        run = RhythmAnalysisRun(
            id=uuid.uuid4(),
            project_id=project_id,
            input_asset_id=asset.id,
            input_hash=plan.source_hash,
            input_role=plan.input_role,
            model_manifest_id=manifest.model_id,
            model_manifest_hash=manifest_hash,
            model_preset=manifest.preset,
            adapter_version=manifest.adapter_version,
            preprocessing_profile="beat-this-logmel-22050-441-v1",
            preprocessing_version=1,
            requested_device=request.device,
            precision="float32",
        )
        self._rhythm.create_run(run)
        thread = threading.Thread(
            target=self._execute_safely,
            args=(run.id, plan, manifest, request),
            name=f"rhythm-run-{run.id}",
            daemon=True,
        )
        thread.start()
        return run

    # -- execution ----------------------------------------------------------
    def _execute_safely(
        self,
        run_id: uuid.UUID,
        plan: RhythmInputPlan,
        manifest: RhythmModelManifest,
        request: RhythmRunRequest,
    ) -> None:
        try:
            self.execute(run_id, plan, manifest, request)
        except Exception:  # noqa: BLE001 - the run row records the failure
            import logging

            logging.getLogger(__name__).exception("rhythm run %s failed", run_id)

    def execute(
        self,
        run_id: uuid.UUID,
        plan: RhythmInputPlan,
        manifest: RhythmModelManifest,
        request: RhythmRunRequest,
    ) -> RhythmAnalysisRun:
        """Execute all pipeline stages for one persisted queued run."""
        run = self._rhythm.get_run(run_id)
        if run is None:
            raise RhythmPipelineError("RHYTHM_RUN_MISSING", "the run row disappeared")
        now = datetime.now(UTC)
        running = run.model_copy(
            update={"status": RhythmAnalysisStatus.RUNNING, "started_at": now}
        )
        self._rhythm.save_run(running)

        work_dir = self._paths.runtime / "rhythm" / str(run_id)
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            asset = self._projects.get_asset(running.input_asset_id)
            if asset is None:
                raise RhythmPipelineError("PROJECT_NOT_READY", "input asset is missing")
            source_path = self._paths.resolve_asset_path(asset.relative_path)
            outcome = asyncio.run(
                prepare_rhythm_input(
                    plan=plan,
                    source_path=source_path,
                    work_dir=work_dir / "input",
                    max_threads=request.threads,
                )
            )
            manifest_hash = rhythm_manifest_hash(manifest)
            checkpoint = self._models.resolve_checkpoint(manifest)
            staging = work_dir / "activation"
            activation_request = ActivationRequest(
                run_id=running.id,
                project_id=running.project_id,
                input_path=outcome.final_path,
                input_hash=outcome.content_hash,
                staging_dir=staging,
                checkpoint_path=checkpoint,
                model_id=manifest.model_id,
                model_manifest_hash=manifest_hash,
                adapter_version=manifest.adapter_version,
                project_sample_rate=plan.sample_rate,
                device=request.device,
                threads=request.threads,
            )
            completed, artifact = run_and_publish(
                run=self._rhythm.get_run(run_id) or running,
                request=activation_request,
                store=RhythmActivationStore(self._paths.data / "rhythm"),
                repository=self._rhythm,
                source_asset_id=asset.id,
                output_semantics="beat/downbeat logits, beat-this final0",
                worker_command=self._worker_command,
            )
            decoded = decode_artifact(
                RhythmActivationStore(self._paths.data / "rhythm"),
                artifact,
                project_sample_rate=plan.sample_rate,
                source_duration_frames=asset.audio.frame_count if asset.audio else 0,
            )
            result = publish_decoded_result(completed, decoded, self._rhythm)

            warnings: list[str] = []
            tempo_map = None
            meter_map = None
            try:
                tempo_map = build_automatic_tempo_map(
                    result.accepted_pulses,
                    project_id=running.project_id,
                    project_sample_rate=plan.sample_rate,
                    source_duration_frames=result.source_duration_frames,
                )
                if map_round_trip_error_frames(tempo_map) > 1:
                    warnings.append("tempo-map round-trip error exceeds one frame")
            except Exception as exc:  # noqa: BLE001 - decoded result stays usable
                warnings.append(f"tempo map unavailable: {exc}")
            if tempo_map is not None:
                try:
                    features = extract_meter_features(
                        source_path=outcome.final_path,
                        source_hash=outcome.content_hash,
                        store=MeterFeatureStore(self._paths.data / "rhythm" / "meter"),
                    )
                    store = MeterFeatureStore(self._paths.data / "rhythm" / "meter")
                    accent, onset = store.load(features)
                    automatic = infer_meter(
                        project_id=running.project_id,
                        tempo_map=tempo_map,
                        pulses=result.accepted_pulses,
                        feature_artifact=features,
                        accent=accent,
                        onset=onset,
                    )
                    regions = [
                        ManualMeterRegion(
                            start=selection.start,
                            candidate=selection.candidate,
                            origin="automatic",
                            confidence=selection.confidence,
                            uncertain=selection.uncertain,
                            alternatives=[],
                        )
                        for selection in automatic.selections
                    ]
                    meter_map = build_meter_map(regions)
                except Exception as exc:  # noqa: BLE001 - keep the decoded grid
                    warnings.append(f"meter inference unavailable: {exc}")

            # The automatic meter selection may start after musical zero
            # (the first pulses are phase evidence). The numbered bar must
            # begin at the first region, otherwise the grid and metronome
            # reject the branch as not starting on a bar boundary.
            origin = automatic_bar_origin(meter_map)
            branch = create_branch_from_result(
                result,
                self._rhythm,
                tempo_map=tempo_map,
                meter_map=meter_map,
                bar_origin=origin,
            )
            activate_branch(self._projects, self._rhythm, branch.id)
            state = self._projects.get_project(running.project_id)
            if state is not None:
                self._projects.set_rhythm_state(
                    state.id,
                    state.rhythm_state.model_copy(
                        update={
                            "active_automatic_result_id": result.id,
                            "display_mode": RhythmDisplayMode.EDITED,
                        }
                    ),
                )
            final = completed.model_copy(
                update={
                    "decoded_result_id": result.id,
                    "warnings": warnings,
                    "actual_device": "cpu" if request.device == "cpu" else None,
                }
            )
            self._rhythm.save_run(final)
            return final
        except Exception as exc:  # noqa: BLE001 - persist the terminal failure
            failed = (self._rhythm.get_run(run_id) or running).model_copy(
                update={
                    "status": RhythmAnalysisStatus.FAILED,
                    "ended_at": datetime.now(UTC),
                    "warnings": [f"{type(exc).__name__}: {exc}"[:500]],
                }
            )
            self._rhythm.save_run(failed)
            raise
        finally:
            import shutil

            shutil.rmtree(work_dir, ignore_errors=True)
