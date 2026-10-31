"""Versioned project persistence, reopen and debounced autosave.

The project store (``projects.ProjectStore``) already writes atomically. This
module owns the *practice state* that sits in ``project.document``: sections,
loop, speed, pitch, position, mixer channels and analysis references. Keeping
the state in one versioned block means a future schema change has a single
migration point, while unknown document keys are preserved untouched.

Autosave is a debounce in front of the same atomic store: repeated edits are
coalesced into one write, and a failed write is recorded without corrupting the
previous JSON.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from basseparate.projects import Project, ProjectStore

CURRENT_STATE_VERSION = 1
DEFAULT_AUTOSAVE_SECONDS = 0.25


class PersistenceError(RuntimeError):
    """The saved practice state cannot be read or written."""


class StateVersionError(PersistenceError):
    """The document was written by a newer schema than this server knows."""


class MissingAssetError(PersistenceError):
    """A project references an asset that is no longer on disk."""

    def __init__(self, project_id: str, asset_id: str, missing: tuple[str, ...]) -> None:
        detail = ", ".join(missing) if missing else "asset directory"
        super().__init__(
            f"project {project_id} cannot reopen: asset {asset_id} is missing ({detail}); "
            "the project JSON is still readable"
        )
        self.project_id = project_id
        self.asset_id = asset_id
        self.missing = missing


class LoopState(BaseModel):
    model_config = ConfigDict(extra="allow")

    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    repeat_count: int | None = Field(default=None, ge=1)
    fade: bool = True

    @model_validator(mode="after")
    def _ordered(self) -> LoopState:
        if self.end_frame <= self.start_frame:
            raise ValueError("loop end_frame must be after start_frame")
        return self


class SectionState(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1, max_length=64)
    name: str = ""
    start_bar: int = Field(ge=0)
    end_bar: int = Field(ge=0)
    color: str | None = None

    @model_validator(mode="after")
    def _ordered(self) -> SectionState:
        if self.end_bar < self.start_bar:
            raise ValueError("section end_bar must not be before start_bar")
        return self


class AnalysisReference(BaseModel):
    model_config = ConfigDict(extra="allow")

    cache_key: str | None = None
    source_sha256: str | None = None
    sample_rate: int | None = Field(default=None, gt=0)
    bpm: float | None = Field(default=None, gt=0)
    key: str | None = None


class MixerChannel(BaseModel):
    model_config = ConfigDict(extra="allow")

    gain: float = Field(default=1.0, ge=0.0)
    muted: bool = False
    solo: bool = False
    pan: float = Field(default=0.0, ge=-1.0, le=1.0)


class PracticeState(BaseModel):
    """The autosaved part of ``project.document``; unknown keys pass through."""

    model_config = ConfigDict(extra="allow")

    state_version: int = CURRENT_STATE_VERSION
    sections: list[SectionState] = Field(default_factory=list)
    loop: LoopState | None = None
    speed: float = 1.0
    pitch_semitones: float = 0.0
    position_frame: int = 0
    analysis: AnalysisReference | None = None
    mixer: dict[str, MixerChannel] = Field(default_factory=dict)

    @field_validator("speed")
    @classmethod
    def _clamp_speed(cls, value: float) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("speed must be a number")
        return min(2.0, max(0.25, float(value)))

    @field_validator("pitch_semitones")
    @classmethod
    def _clamp_pitch(cls, value: float) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("pitch must be a number")
        return min(12.0, max(-12.0, float(value)))

    @field_validator("position_frame")
    @classmethod
    def _non_negative_position(cls, value: int) -> int:
        return max(0, int(value))


@dataclass(frozen=True)
class ReopenedProject:
    project: Project
    state: PracticeState


def _analysis_reference(value: object) -> AnalysisReference | None:
    if value is None:
        return None
    if isinstance(value, str):
        return AnalysisReference(cache_key=value)
    if isinstance(value, Mapping):
        return AnalysisReference.model_validate(dict(value))
    raise PersistenceError(f"analysis reference is not an object: {value!r}")


def migrate_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy at the current state version.

    Version 0 is the pre-persistence shape used by the first project store and
    the early UI: sections/loop/speed/pitch already live at the top level but
    there is no ``state_version`` marker. The migration is intentionally
    additive; unknown keys survive.
    """
    migrated = dict(document)
    raw_version = migrated.get("state_version", 0)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int):
        raise PersistenceError(f"state_version must be an integer, got {raw_version!r}")
    if raw_version > CURRENT_STATE_VERSION:
        raise StateVersionError(
            f"project state version {raw_version} is newer than this server supports "
            f"({CURRENT_STATE_VERSION})"
        )
    if raw_version < 0:
        raise PersistenceError(f"state_version must not be negative, got {raw_version}")
    migrated["state_version"] = CURRENT_STATE_VERSION
    return migrated


def restore_state(document: Mapping[str, Any]) -> PracticeState:
    """Read the practice state from a project document, migrating if needed."""
    migrated = migrate_document(document)
    try:
        return PracticeState.model_validate(
            {
                "state_version": migrated["state_version"],
                "sections": migrated.get("sections", []),
                "loop": migrated.get("loop"),
                "speed": migrated.get("speed", 1.0),
                "pitch_semitones": migrated.get("pitch_semitones", migrated.get("pitch", 0.0)),
                "position_frame": migrated.get("position_frame", 0),
                "analysis": _analysis_reference(
                    migrated.get("analysis", migrated.get("analysis_reference"))
                ),
                "mixer": migrated.get("mixer", {}),
            }
        )
    except ValidationError as error:
        raise PersistenceError(f"project state is invalid: {error}") from error


def document_with_state(document: Mapping[str, Any], state: PracticeState) -> dict[str, Any]:
    """Merge the practice state into an existing document, preserving unknown keys."""
    merged = migrate_document(document)
    merged.update(state.model_dump(mode="json"))
    merged["state_version"] = CURRENT_STATE_VERSION
    return merged


class ProjectPersistence:
    """A store plus the asset root, exposing reopen and state autosave."""

    def __init__(self, store: ProjectStore, assets_root: Path) -> None:
        self.store = store
        self.assets_root = Path(assets_root)

    def load_state(self, project_id: str) -> ReopenedProject:
        project = self.store.get(project_id)
        return ReopenedProject(project=project, state=restore_state(project.document))

    def save_state(
        self,
        project_id: str,
        state: PracticeState,
        *,
        expected_revision: int | None = None,
    ) -> Project:
        project = self.store.get(project_id)
        document = document_with_state(project.document, state)
        return self.store.save(
            project.model_copy(update={"document": document}),
            expected_revision=expected_revision,
        )

    def missing_assets(self, project: Project) -> list[str]:
        """Asset files referenced by the project that are not on disk."""
        asset_root = self.assets_root / project.audio.asset_id
        missing: list[str] = []
        if not asset_root.is_dir():
            return [f"assets/{project.audio.asset_id} (directory)"]
        pcm = asset_root / "pcm.f32"
        if not pcm.is_file():
            missing.append(f"assets/{project.audio.asset_id}/pcm.f32")
        if not any(asset_root.glob("source.*")):
            missing.append(f"assets/{project.audio.asset_id}/source.*")
        for bucket in project.audio.peaks:
            peaks = asset_root / f"peaks-{bucket}.bin"
            if not peaks.is_file():
                missing.append(f"assets/{project.audio.asset_id}/{peaks.name}")
        return missing

    def reopen(self, project_id: str) -> ReopenedProject:
        reopened = self.load_state(project_id)
        missing = self.missing_assets(reopened.project)
        if missing:
            raise MissingAssetError(project_id, reopened.project.audio.asset_id, tuple(missing))
        return reopened

    def autosave(
        self,
        project_id: str,
        *,
        delay_seconds: float = DEFAULT_AUTOSAVE_SECONDS,
        scheduler: Scheduler | None = None,
        on_error: Callable[[BaseException], None] | None = None,
    ) -> DebouncedAutosave:
        return DebouncedAutosave(
            self,
            project_id,
            delay_seconds=delay_seconds,
            scheduler=scheduler,
            on_error=on_error,
        )


class TimerHandle(Protocol):
    def cancel(self) -> None: ...


class Scheduler(Protocol):
    def __call__(self, delay_seconds: float, callback: Callable[[], None]) -> TimerHandle: ...


def _thread_timer(delay_seconds: float, callback: Callable[[], None]) -> TimerHandle:
    timer = threading.Timer(delay_seconds, callback)
    timer.daemon = True
    timer.start()
    return timer


class DebouncedAutosave:
    """Coalesce practice-state edits into one atomic write.

    ``schedule`` replaces the pending state and restarts the timer; ``flush``
    writes now (also used by ``close``). A failed background write is stored in
    ``last_error`` and leaves the previous JSON untouched, so the next edit can
    retry. The scheduler is injectable so tests do not sleep.
    """

    def __init__(
        self,
        persistence: ProjectPersistence,
        project_id: str,
        *,
        delay_seconds: float = DEFAULT_AUTOSAVE_SECONDS,
        scheduler: Scheduler | None = None,
        on_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        if delay_seconds < 0:
            raise ValueError("delay_seconds must not be negative")
        self.persistence = persistence
        self.project_id = project_id
        self.delay_seconds = delay_seconds
        self._scheduler: Scheduler = scheduler if scheduler is not None else _thread_timer
        self._on_error = on_error
        self._lock = threading.Lock()
        self._timer: TimerHandle | None = None
        self._pending: PracticeState | None = None
        self._last_saved: Project | None = None
        self._last_error: str | None = None

    @property
    def pending(self) -> bool:
        with self._lock:
            return self._pending is not None

    @property
    def last_saved(self) -> Project | None:
        with self._lock:
            return self._last_saved

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def schedule(self, state: PracticeState) -> None:
        with self._lock:
            self._pending = state
            if self._timer is not None:
                self._timer.cancel()
            self._timer = self._scheduler(self.delay_seconds, self._save_pending)

    def flush(self) -> Project | None:
        with self._lock:
            timer = self._timer
            self._timer = None
            if timer is not None:
                timer.cancel()
            state = self._pending
            self._pending = None
        if state is None:
            with self._lock:
                return self._last_saved
        try:
            project = self.persistence.save_state(self.project_id, state)
        except BaseException:
            # Keep the state pending so a later flush can retry it; a newer
            # schedule must win if one arrived while the write was failing.
            with self._lock:
                if self._pending is None:
                    self._pending = state
            raise
        with self._lock:
            self._last_saved = project
            self._last_error = None
        return project

    def close(self) -> Project | None:
        return self.flush()

    def _save_pending(self) -> None:
        try:
            self.flush()
        except BaseException as error:  # background timer boundary
            with self._lock:
                self._last_error = str(error)
            if self._on_error is not None:
                self._on_error(error)
