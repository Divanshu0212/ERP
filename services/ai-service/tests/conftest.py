"""Shared test fixtures — a FastAPI TestClient (sync) for the app."""

import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
