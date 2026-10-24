"""Export the project and worker JSON Schemas (M3.17 §19.10).

The project schema is the persisted project record surface shared with
portable projects; the worker schema pins the job message payloads. Both
are generated from the Pydantic models, never hand-written.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from basseparate.domain.project import ProjectRecord  # noqa: E402
from basseparate.worker import protocol  # noqa: E402


def _canonical(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def project_schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://basseparate.local/schemas/project.schema.json",
        "title": "ProjectRecord",
        "project_schema_version": ProjectRecord.model_fields["schema_version"].default,
        **ProjectRecord.model_json_schema(),
    }


def worker_schema() -> dict[str, object]:
    names = (
        "HelloMessage",
        "DescribeMessage",
        "CapabilitiesMessage",
        "PingMessage",
        "PongMessage",
        "ShutdownMessage",
        "StoppedMessage",
        "ErrorMessage",
        "RunMessage",
        "ProgressMessage",
        "CompletedMessage",
        "FailedMessage",
        "CancelMessage",
        "CancelledMessage",
    )
    messages = {
        name: getattr(protocol, name).model_json_schema(ref_template="#/$defs/{model}")
        for name in names
    }
    defs: dict[str, object] = {}
    for schema in messages.values():
        defs.update(schema.get("$defs", {}))
        schema.pop("$defs", None)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://basseparate.local/schemas/worker.schema.json",
        "title": "WorkerProtocol",
        "protocol_version": protocol.PROTOCOL_VERSION,
        "messages": messages,
        "$defs": defs,
    }


def main() -> int:
    contracts = ROOT / "contracts"
    generated = {
        contracts / "project.schema.json": _canonical(project_schema()),
        contracts / "worker.schema.json": _canonical(worker_schema()),
    }
    if "--check" in sys.argv:
        stale = [
            path
            for path, content in generated.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != content
        ]
        if stale:
            for path in stale:
                print(f"FAIL: {path.relative_to(ROOT)} is out of date.")
            print("Regenerate with: .venv/bin/python scripts/export_schemas.py")
            return 1
        print("OK: project and worker schemas are in sync.")
        return 0
    contracts.mkdir(exist_ok=True)
    for path, content in generated.items():
        path.write_text(content, encoding="utf-8")
        print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
