"""Unit tests for the media worker memory bound (M2.12, spec §14.3)."""

from __future__ import annotations

import sys

import pytest

from basseparate.worker import media_worker_command
from basseparate.worker.media_worker import apply_memory_limit

MIB = 1024 * 1024


class _FakeResource:
    """Stands in for the ``resource`` module in ``sys.modules``."""

    RLIMIT_AS = 1
    RLIM_INFINITY = -1

    def __init__(self, soft: int, hard: int, *, refuse: bool = False) -> None:
        self.soft = soft
        self.hard = hard
        self.refuse = refuse
        self.set_limits: tuple[int, int] | None = None

    def getrlimit(self, which: int) -> tuple[int, int]:
        return self.soft, self.hard

    def setrlimit(self, which: int, limits: tuple[int, int]) -> None:
        if self.refuse:
            raise OSError("refused by the OS")
        self.set_limits = limits


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeResource) -> None:
    monkeypatch.setitem(sys.modules, "resource", fake)


class TestApplyMemoryLimit:
    def test_none_is_a_noop(self) -> None:
        assert apply_memory_limit(None) is None
        assert apply_memory_limit(0) is None
        assert apply_memory_limit(-5) is None

    def test_sets_the_limit_when_unbounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeResource(_FakeResource.RLIM_INFINITY, _FakeResource.RLIM_INFINITY)
        _install(monkeypatch, fake)
        assert apply_memory_limit(2048) == 2048 * MIB
        assert fake.set_limits == (2048 * MIB, _FakeResource.RLIM_INFINITY)

    def test_keeps_a_stricter_existing_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeResource(512 * MIB, _FakeResource.RLIM_INFINITY)
        _install(monkeypatch, fake)
        assert apply_memory_limit(4096) == 512 * MIB
        assert fake.set_limits is None

    def test_clamps_to_a_finite_hard_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeResource(_FakeResource.RLIM_INFINITY, 1024 * MIB)
        _install(monkeypatch, fake)
        assert apply_memory_limit(4096) == 1024 * MIB
        assert fake.set_limits == (1024 * MIB, 1024 * MIB)

    def test_refused_change_is_not_fatal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeResource(_FakeResource.RLIM_INFINITY, _FakeResource.RLIM_INFINITY, refuse=True)
        _install(monkeypatch, fake)
        assert apply_memory_limit(4096) is None

    def test_missing_resource_module_is_not_fatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "resource", None)
        assert apply_memory_limit(4096) is None


class TestWorkerCommand:
    def test_default_command_has_no_flag(self) -> None:
        assert "--memory-limit-mb" not in media_worker_command()

    def test_memory_limit_is_passed_to_the_child(self) -> None:
        base = media_worker_command()
        limited = media_worker_command(2048)
        assert limited[: len(base)] == base
        assert limited[-2:] == ["--memory-limit-mb", "2048"]
