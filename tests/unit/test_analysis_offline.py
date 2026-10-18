"""Analysis runner offline guards (M2.17/M2.18, spec §4.1, §20.1).

Inference must never retrieve model bytes: the runner sets the
Hugging Face/Transformers offline flags before importing torch or
loading the model, and the protocol worker never imports torch at
startup.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_runner_disables_network_before_torch_and_model_load() -> None:
    source = (REPO_ROOT / "analysis" / "separate.py").read_text(encoding="utf-8")
    offline = source.index('os.environ["HF_HUB_OFFLINE"] = "1"')
    transformers_offline = source.index('os.environ["TRANSFORMERS_OFFLINE"] = "1"')
    torch_import = source.index("import torch", offline)
    model_load = source.index("get_model(", offline)
    assert offline < torch_import < model_load
    assert transformers_offline < torch_import < model_load


def test_worker_startup_does_not_import_torch() -> None:
    source = (REPO_ROOT / "analysis" / "worker.py").read_text(encoding="utf-8")
    assert "import torch" not in source
    assert "import demucs" not in source
