from __future__ import annotations

import hashlib
import importlib.util
import struct
import sys
from pathlib import Path

import pytest


def _load():
    path = Path(__file__).resolve().parents[2] / "scripts" / "install_tools.py"
    spec = importlib.util.spec_from_file_location("install_tools", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


installer = _load()


def test_pinned_plugin_manifest_is_complete() -> None:
    names = {f"embed-{blob.index:02d}-{blob.offset}.so" for blob in installer.PLUGIN_BLOBS}
    assert installer.CHORDINO in names
    assert installer.KEY_AND_BEAT in names
    assert installer.BEATROOT in names
    assert len({blob.offset for blob in installer.PLUGIN_BLOBS}) == len(installer.PLUGIN_BLOBS)
    assert all(len(blob.sha256) == 64 for blob in installer.PLUGIN_BLOBS)


def test_elf_extent_reads_the_program_header_table(tmp_path: Path) -> None:
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4] = 2  # 64-bit
    header[5] = 1  # little endian
    struct.pack_into("<Q", header, 0x20, 64)  # e_phoff
    struct.pack_into("<H", header, 0x36, 56)  # e_phentsize
    struct.pack_into("<H", header, 0x38, 1)  # e_phnum
    program = bytearray(56)
    struct.pack_into("<Q", program, 0x08, 128)  # p_offset
    struct.pack_into("<Q", program, 0x20, 16)  # p_filesz
    data = bytes(header) + bytes(program) + bytes(112)
    assert installer.elf_extent(data, 0) == 144


def test_verify_rejects_a_bad_checksum(tmp_path: Path) -> None:
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"basseparate")
    with pytest.raises(installer.InstallError, match="checksum mismatch"):
        installer._verify(path, hashlib.sha256(b"other").hexdigest())


def test_download_refuses_plain_http(tmp_path: Path) -> None:
    with pytest.raises(installer.InstallError, match="non-HTTPS"):
        installer._download("http://example.invalid/file", tmp_path / "file", "0" * 64)


def test_model_is_skipped_without_consent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_dir = tmp_path / "models"
    monkeypatch.setattr(installer, "MODEL_DIR", model_dir)
    monkeypatch.setattr(installer, "CHECKPOINTS", tmp_path / "checkpoints.json")
    (tmp_path / "checkpoints.json").write_text(
        '{"checkpoints": {}, "channels": 2, "preset": "htdemucs_ft"}', encoding="utf-8"
    )
    monkeypatch.setattr(installer.sys.stdin, "isatty", lambda: False)
    assert installer.install_model(accept_terms=False, force=False) is False
    assert not model_dir.exists()
