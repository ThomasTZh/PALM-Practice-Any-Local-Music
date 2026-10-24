"""Contract drift check (M0.8).

Regenerates OpenAPI + TypeScript types into a temp directory and
compares against checked-in artifacts. Fails if they differ.
Does not require Git.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _canonical_json(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def main() -> int:
    # 1. Regenerate OpenAPI into temp dir.
    with tempfile.TemporaryDirectory(prefix="basseparate-contract-") as tmp:
        tmp_path = Path(tmp)
        gen_script = tmp_path / "export.py"
        gen_script.write_text(
            f"""
import json, sys
from pathlib import Path
sys.path.insert(0, str({str(ROOT / 'src')!r}))
from basseparate.config import resolve_config
from basseparate.app import create_app
config = resolve_config(env={{}}, cli={{}})
app = create_app(config)
schema = app.openapi()
schema.pop("servers", None)
out = Path({str(tmp_path / 'openapi.json')!r})
out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
""",
            encoding="utf-8",
        )

        # Run with project venv python.
        venv_python = ROOT / ".venv" / "bin" / "python"
        if not venv_python.exists():
            print("ERROR: .venv not found. Run `uv sync` first.")
            return 1

        result = subprocess.run(
            [str(venv_python), str(gen_script)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"ERROR: OpenAPI generation failed:\n{result.stderr}")
            return 1

        generated_openapi = (tmp_path / "openapi.json").read_text(encoding="utf-8")
        checked_in_openapi = (ROOT / "contracts" / "openapi.json").read_text(encoding="utf-8")

        # 2. Compare OpenAPI (deterministic: sorted keys, no timestamps).
        if _canonical_json(json.loads(generated_openapi)) != _canonical_json(
            json.loads(checked_in_openapi)
        ):
            print("FAIL: contracts/openapi.json is out of date.")
            print("Regenerate with: uv run --locked python scripts/export_openapi.py")
            return 1

        # 3. Regenerate TypeScript types into temp dir.
        gen_ts = tmp_path / "schema.ts"
        frontend_dir = ROOT / "frontend"
        pnpm = subprocess.run(
            [
                "pnpm",
                "--dir",
                str(frontend_dir),
                "exec",
                "openapi-typescript",
                str(tmp_path / "openapi.json"),
                "-o",
                str(gen_ts),
            ],
            capture_output=True,
            text=True,
            env={"PATH": f"{Path.home()}/.npm-global/bin:/usr/bin:/bin"},
        )
        if pnpm.returncode != 0:
            print(f"ERROR: TypeScript generation failed:\n{pnpm.stderr}")
            return 1

        generated_ts = gen_ts.read_text(encoding="utf-8")
        checked_in_ts = (frontend_dir / "src" / "api" / "schema.ts").read_text(encoding="utf-8")

        # 4. Compare TypeScript (strip line endings for stability).
        if generated_ts.strip() != checked_in_ts.strip():
            print("FAIL: frontend/src/api/schema.ts is out of date.")
            print(
                "Regenerate with: uv run --locked python scripts/export_openapi.py"
                " && pnpm --dir frontend run contracts"
            )
            return 1

    schema_check = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "scripts" / "export_schemas.py"), "--check"],
        capture_output=True,
        text=True,
    )
    if schema_check.returncode != 0:
        print(schema_check.stdout.strip())
        print(schema_check.stderr.strip())
        return 1
    print(schema_check.stdout.strip())

    print("OK: contract artifacts are in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
