"""Persisted model-bundle verification results (M2.17, spec §19.1).

``POST /api/v1/models/{id}/verify`` hashes the bundled artifacts against
the registry (local only, no network) and records the outcome here so
``GET /api/v1/models`` can report it without re-hashing every bundle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from basseparate.models.bundle import BundleError, BundleReport

#: JSON document version for the verification store.
VERIFICATION_STORE_VERSION = 1


@dataclass(frozen=True, slots=True)
class VerificationRecord:
    """One recorded bundle verification."""

    model_id: str
    state: str
    missing: tuple[str, ...]
    corrupt: tuple[str, ...]
    verified_at: str


class VerificationStore:
    """JSON persistence of the last verification per model.

    A missing file means "never verified" and is never an error.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, VerificationRecord]:
        if not self._path.exists():
            return {}
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BundleError(
                f"cannot read model verification store {self._path}: {exc}"
            ) from exc
        if (
            not isinstance(document, dict)
            or document.get("version") != VERIFICATION_STORE_VERSION
        ):
            raise BundleError(
                f"model verification store {self._path} has an unsupported version"
            )
        raw_models = document.get("models", {})
        if not isinstance(raw_models, dict):
            raise BundleError(f"model verification store {self._path} is malformed")
        records: dict[str, VerificationRecord] = {}
        for model_id, raw in raw_models.items():
            if not isinstance(raw, dict):
                raise BundleError(f"model verification entry {model_id!r} is malformed")
            records[str(model_id)] = VerificationRecord(
                model_id=str(model_id),
                state=str(raw.get("state", "missing")),
                missing=tuple(str(name) for name in raw.get("missing", [])),
                corrupt=tuple(str(name) for name in raw.get("corrupt", [])),
                verified_at=str(raw.get("verified_at", "")),
            )
        return records

    def save(self, records: dict[str, VerificationRecord]) -> None:
        document = {
            "version": VERIFICATION_STORE_VERSION,
            "models": {
                model_id: {
                    "state": record.state,
                    "missing": list(record.missing),
                    "corrupt": list(record.corrupt),
                    "verified_at": record.verified_at,
                }
                for model_id, record in sorted(records.items())
            },
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(self._path)

    def record(
        self, report: BundleReport, now: datetime | None = None
    ) -> VerificationRecord:
        timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat().replace(
            "+00:00", "Z"
        )
        record = VerificationRecord(
            model_id=report.model_id,
            state=report.state,
            missing=report.missing,
            corrupt=report.corrupt,
            verified_at=timestamp,
        )
        records = self.load()
        records[report.model_id] = record
        self.save(records)
        return record
