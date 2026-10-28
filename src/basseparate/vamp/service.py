"""Application service for local Vamp rhythm analysis."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from basseparate.domain.project import ProjectRecord
from basseparate.domain.rhythm import RhythmBranchRecord, RhythmDisplayMode
from basseparate.storage.paths import StoragePaths
from basseparate.storage.repository import ProjectRepository, RhythmRepository
from basseparate.vamp.features import SUPPORTED_BPB, VampAnalysis
from basseparate.vamp.grid import build_branch_from_vamp
from basseparate.vamp.host import VampHostConfig, analyze_pcm
from basseparate.vamp.native import analyze_pcm_native


class VampUnavailable(RuntimeError):
    """The local Vamp host/plugin installation is not configured."""


class VampAnalysisError(RuntimeError):
    """A Vamp analysis could not be completed."""


@dataclass(frozen=True, slots=True)
class VampAnalysisResult:
    branch: RhythmBranchRecord
    beats: int
    bars: int
    cached: bool
    plugin_key: str
    plugin_version: str
    bpb: int


class VampAnalysisService:
    """Synchronous, cached QM bar/beat analysis.

    One service instance is shared by the app. A per-project lock prevents
    two analyses from racing to publish branches for the same project.
    """

    def __init__(
        self,
        *,
        storage_paths: StoragePaths,
        repository: ProjectRepository,
        rhythm_repository: RhythmRepository,
        server_path: str,
        plugin_path: str,
        library_path: str,
        timeout_seconds: float = 300.0,
        native_host_path: str = "",
    ) -> None:
        self._storage_paths = storage_paths
        self._repository = repository
        self._rhythm_repository = rhythm_repository
        self._server_path = Path(server_path).expanduser() if server_path else None
        self._plugin_path = Path(plugin_path).expanduser() if plugin_path else None
        self._library_path = Path(library_path).expanduser() if library_path else None
        self._native_host_path = Path(native_host_path).expanduser() if native_host_path else None
        self._timeout_seconds = timeout_seconds
        self._locks: dict[uuid.UUID, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, project_id: uuid.UUID) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(project_id, threading.Lock())

    def _cache_path(self, project: ProjectRecord, source_hash: str, bpb: int) -> Path:
        key = hashlib.sha256(
            f"{source_hash}|qm-vamp-plugins:qm-barbeattracker|bpb={bpb}".encode()
        ).hexdigest()
        return self._storage_paths.cache / "vamp" / f"{key}.json"

    def analyze(self, project_id: uuid.UUID, bpb: int = 4) -> VampAnalysisResult:
        if bpb not in SUPPORTED_BPB:
            raise VampAnalysisError(
                "bpb must be one of " + ", ".join(str(value) for value in sorted(SUPPORTED_BPB))
            )
        if self._plugin_path is None or (
            self._native_host_path is None and self._server_path is None
        ):
            raise VampUnavailable(
                "Vamp analysis is not configured; set BASSEPARATE_VAMP_SERVER "
                "and BASSEPARATE_VAMP_PLUGIN_PATH"
            )
        with self._lock_for(project_id):
            project = self._repository.get_project(project_id)
            if project is None:
                raise VampAnalysisError(f"project {project_id} does not exist")
            if project.canonical_asset_id is None or project.sample_rate is None:
                raise VampAnalysisError("a ready project with canonical audio is required")
            asset = self._repository.get_asset(project.canonical_asset_id)
            if asset is None or asset.audio is None:
                raise VampAnalysisError("the canonical audio asset is missing")
            pcm_path = self._storage_paths.resolve_asset_path(asset.relative_path)
            cache_path = self._cache_path(project, asset.content_hash, bpb)
            cached = cache_path.is_file()
            if cached:
                try:
                    analysis = VampAnalysis.from_payload(
                        json.loads(cache_path.read_text(encoding="utf-8"))
                    )
                except (ValueError, OSError, json.JSONDecodeError):
                    cached = False
            if not cached:
                try:
                    if self._native_host_path is not None:
                        analysis = analyze_pcm_native(
                            pcm_path,
                            sample_rate=project.sample_rate,
                            channels=asset.audio.channel_count,
                            host_path=self._native_host_path,
                            plugin_path=self._plugin_path,
                            plugin_key="qm-vamp-plugins:qm-barbeattracker",
                            bpb=bpb,
                            timeout_seconds=self._timeout_seconds,
                        )
                    else:
                        assert self._server_path is not None
                        config = VampHostConfig(
                            server_path=self._server_path,
                            plugin_path=self._plugin_path,
                            library_path=self._library_path,
                            bpb=bpb,
                            timeout_seconds=self._timeout_seconds,
                        )
                        analysis = analyze_pcm(
                            pcm_path,
                            sample_rate=project.sample_rate,
                            channels=asset.audio.channel_count,
                            config=config,
                        )
                except Exception as exc:
                    raise VampAnalysisError(str(exc)) from exc
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = cache_path.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(analysis.to_payload(), sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                temporary.replace(cache_path)
            branch = build_branch_from_vamp(project, analysis)
            self._rhythm_repository.create_branch(branch)
            state = project.rhythm_state.model_copy(
                update={
                    "active_branch_id": branch.id,
                    "active_automatic_result_id": None,
                    "display_mode": RhythmDisplayMode.EDITED,
                }
            )
            self._repository.set_rhythm_state(project_id, state)
            return VampAnalysisResult(
                branch=branch,
                beats=len(analysis.beats),
                bars=len(analysis.bars),
                cached=cached,
                plugin_key=analysis.plugin_key,
                plugin_version=analysis.plugin_version,
                bpb=bpb,
            )
