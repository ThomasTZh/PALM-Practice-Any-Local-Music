"""Shared app/client helpers for the export and reopen integration tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from basseparate.app import create_app
from basseparate.config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data", web_dir=tmp_path / "dist")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def fresh_client(settings: Settings) -> TestClient:
    """A new app + store over the same data root, i.e. a service restart."""
    return TestClient(create_app(settings))
