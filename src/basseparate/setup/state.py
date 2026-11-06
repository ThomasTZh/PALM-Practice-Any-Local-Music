"""Persistent setup state below the writable data root."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from basseparate.config import RuntimePaths, runtime_paths


class SetupStateStore:
    def __init__(self, runtime: RuntimePaths | None = None) -> None:
        self.runtime = runtime or runtime_paths()

    @property
    def path(self) -> Path:
        return self.runtime.setup_state

    def load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def save(self, state: dict[str, Any]) -> dict[str, Any]:
        self.runtime.ensure_data_path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary).replace(self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return state

    def skip(self, skipped: bool) -> dict[str, Any]:
        state = self.load()
        state["skipped"] = bool(skipped)
        return self.save(state)

    def record(self, action: str, **values: object) -> dict[str, Any]:
        state = self.load()
        history = state.get("history")
        if not isinstance(history, list):
            history = []
        history.append({"action": action, **values})
        state["history"] = history[-50:]
        state[f"{action}_completed"] = True
        return self.save(state)
