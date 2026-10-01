"""Unit tests for ImportRecord and ProbeResult schemas (M1.1)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from basseparate.domain.import_record import (
    AudioStreamInfo,
    ImportRecord,
    ProbeResult,
    TransferState,
)

NOW = datetime(2025, 1, 1, tzinfo=UTC)
FAKE_HASH = "c" * 64


def _make_stream(**overrides: object) -> AudioStreamInfo:
    base: dict[str, object] = {
        "index": 0,
        "codec": "pcm_s16le",
        "sample_rate": 48_000,
        "channel_count": 2,
        "channel_layout": "stereo",
    }
    base.update(overrides)
    return AudioStreamInfo(**base)


def _make_probe(**overrides: object) -> ProbeResult:
    base: dict[str, object] = {
        "format_name": "wav",
        "byte_count": 1_000_000,
        "ffmpeg_version": "8.1.2",
        "ffprobe_version": "8.1.2",
        "audio_streams": (_make_stream(),),
    }
    base.update(overrides)
    return ProbeResult(**base)


def _make_import(**overrides: object) -> ImportRecord:
    base: dict[str, object] = {
        "id": uuid4(),
        "project_id": uuid4(),
        "filename": "take_final.wav",
        "declared_byte_count": 1_000_000,
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return ImportRecord(**base)


class TestAudioStreamInfo:
    def test_basic_stream(self) -> None:
        s = _make_stream()
        assert s.index == 0
        assert s.is_default is False
        assert s.language is None

    def test_stream_with_all_metadata(self) -> None:
        s = _make_stream(
            index=3,
            language="eng",
            title="Main mix",
            is_default=True,
            estimated_duration_seconds=120.5,
            start_timestamp_seconds=0.023,
        )
        assert s.index == 3
        assert s.is_default is True

    def test_negative_index_rejected(self) -> None:
        with pytest.raises(ValidationError, match="index"):
            _make_stream(index=-1)

    def test_bad_language_rejected(self) -> None:
        with pytest.raises(ValidationError, match="language"):
            _make_stream(language="x")


class TestProbeResult:
    def test_basic_probe(self) -> None:
        p = _make_probe()
        assert p.format_name == "wav"
        assert len(p.audio_streams) == 1

    def test_no_audio_streams(self) -> None:
        p = _make_probe(audio_streams=())
        assert p.audio_streams == ()

    def test_probe_serialization_roundtrip(self) -> None:
        p = _make_probe(title="Track", artist="Artist")
        data = p.model_dump(mode="json")
        restored = ProbeResult.model_validate(data)
        assert restored == p


class TestImportRecord:
    def test_fresh_import(self) -> None:
        i = _make_import()
        assert i.transfer_state == TransferState.CREATED
        assert i.received_byte_count == 0
        assert i.source_sha256 is None
        assert i.probe_result is None
        assert i.selected_stream_index is None
        assert i.job_ids == ()

    def test_uploading_import(self) -> None:
        i = _make_import(transfer_state=TransferState.UPLOADING, received_byte_count=500)
        assert i.received_byte_count == 500

    def test_complete_import_requires_hash_and_full_bytes(self) -> None:
        with pytest.raises(ValidationError, match="source_sha256"):
            _make_import(transfer_state=TransferState.COMPLETE)
        with pytest.raises(ValidationError, match="declared"):
            _make_import(
                transfer_state=TransferState.COMPLETE,
                source_sha256=FAKE_HASH,
                received_byte_count=999,
            )
        i = _make_import(
            transfer_state=TransferState.COMPLETE,
            source_sha256=FAKE_HASH,
            received_byte_count=1_000_000,
        )
        assert i.transfer_state == TransferState.COMPLETE

    def test_cancelled_import_requires_error(self) -> None:
        with pytest.raises(ValidationError, match="error"):
            _make_import(transfer_state=TransferState.CANCELLED)
        i = _make_import(transfer_state=TransferState.CANCELLED, error="user cancelled")
        assert i.error == "user cancelled"

    def test_received_cannot_exceed_declared(self) -> None:
        with pytest.raises(ValidationError, match="exceed"):
            _make_import(received_byte_count=1_000_001)

    def test_filename_validation(self) -> None:
        with pytest.raises(ValidationError, match="filename"):
            _make_import(filename="")
        with pytest.raises(ValidationError, match="control"):
            _make_import(filename="bad\x00name.wav")
        i = _make_import(filename="Ünïcodé 文件 (final) v2.mp4")
        assert i.filename == "Ünïcodé 文件 (final) v2.mp4"

    def test_probe_and_stream_selection(self) -> None:
        probe = _make_probe(
            audio_streams=(
                _make_stream(index=1, codec="mp3", title="Voice"),
                _make_stream(index=2, codec="aac", is_default=True, title="Music"),
            )
        )
        i = _make_import(
            transfer_state=TransferState.COMPLETE,
            source_sha256=FAKE_HASH,
            received_byte_count=1_000_000,
            probe_result=probe,
            selected_stream_index=2,
            job_ids=(uuid4(),),
        )
        assert i.probe_result is not None
        assert len(i.probe_result.audio_streams) == 2
        assert i.selected_stream_index == 2
        assert len(i.job_ids) == 1

    def test_serialization_roundtrip(self) -> None:
        i = _make_import(
            transfer_state=TransferState.COMPLETE,
            source_sha256=FAKE_HASH,
            received_byte_count=1_000_000,
            probe_result=_make_probe(),
        )
        data = i.model_dump(mode="json")
        assert isinstance(data["id"], str)
        restored = ImportRecord.model_validate(data)
        assert restored == i
