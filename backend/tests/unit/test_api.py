import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from src.api.main import app

client = TestClient(app)

@patch('src.api.routers.invoices.get_raw_invoices_container')
@patch('src.api.routers.invoices.get_invoices_container')
@patch('src.api.routers.invoices.get_doc_intel_client')
def test_upload_invoice_auth_required(mock_doc, mock_db, mock_blob):
    # Test that the route requires auth since we wired up Depends(require_user)
    # The frontend is sending this request without an Authorization header
    with open("tests/conftest.py", "rb") as f:
        response = client.post("/invoices/upload", files={"file": ("test.pdf", f, "application/pdf")})
        assert response.status_code == 401

# Add more tests as needed for approvals, etc.
