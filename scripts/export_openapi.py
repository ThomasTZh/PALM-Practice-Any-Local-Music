"""Export OpenAPI schema from the application factory (M0.8).

Runs without starting a server. Writes to contracts/openapi.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from basseparate.app import create_app  # noqa: E402
from basseparate.config import resolve_config  # noqa: E402


def main() -> None:
    config = resolve_config(env={}, cli={})
    app = create_app(config)
    schema = app.openapi()
    # Remove server-specific fields for deterministic output.
    schema.pop("servers", None)
    out = Path(__file__).resolve().parent.parent / "contracts" / "openapi.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
