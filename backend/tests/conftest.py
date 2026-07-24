"""Shared test fixtures.

Sets the handful of settings fields that have no default (see
src/core/config.py) so importing src.api.main doesn't blow up in CI,
where there's no .env file. Keep these as fake-but-valid-shaped
values — never real connection strings.
"""

import os

import pytest

os.environ.setdefault(
    "AZURE_STORAGE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;",
)
os.environ.setdefault("COSMOS_ENDPOINT", "https://localhost:8081")
os.environ.setdefault("COSMOS_KEY", "test-key-not-real")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from src.api.main import app

    return TestClient(app)
