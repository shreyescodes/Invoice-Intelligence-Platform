from unittest.mock import patch, MagicMock
import pytest
from src.core.db import get_cosmos_client, get_blob_service_client

@patch('src.core.db.get_settings')
def test_get_cosmos_client_local(mock_settings):
    mock_settings.return_value.cosmos_endpoint = "https://localhost:8081"
    mock_settings.return_value.cosmos_key = "dummy"
    
    with patch('src.core.db.CosmosClient') as MockClient:
        client = get_cosmos_client()
        MockClient.assert_called_once()
        assert client is not None

@patch('src.core.db.get_settings')
def test_get_blob_service_client_local(mock_settings):
    mock_settings.return_value.azure_storage_connection_string = "UseDevelopmentStorage=true"
    
    with patch('src.core.db.BlobServiceClient') as MockClient:
        client = get_blob_service_client()
        assert client is not None
