from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)

@patch('src.api.routers.invoices.get_raw_invoices_container')
@patch('src.api.routers.invoices.get_invoices_container')
# Fix 4: get_doc_intel_client lives in src.core.extraction, not in invoices.py.
# Patching the wrong path means the real function runs and the test is meaningless.
@patch('src.core.extraction.get_doc_intel_client')
def test_upload_invoice_auth_required(mock_doc, mock_db, mock_blob):
    # In local environment, require_user returns a mock user — so auth passes.
    # This test validates that the upload endpoint rejects invalid file types.
    mock_blob_instance = MagicMock()
    mock_blob.return_value.get_blob_client.return_value = mock_blob_instance
    mock_db.return_value.create_item.return_value = {}

    response = client.post(
        "/invoices/upload",
        files={"file": ("test.exe", b"fake-binary-content", "application/octet-stream")}
    )
    # Should be rejected due to invalid MIME type guard
    assert response.status_code == 400
    assert "Invalid file type" in response.json()["detail"]


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
