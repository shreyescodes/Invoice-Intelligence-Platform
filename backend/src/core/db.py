"""Database and Storage clients."""
import logging

from azure.cosmos import CosmosClient
from azure.storage.blob import BlobServiceClient

from src.core.config import get_settings

logger = logging.getLogger(__name__)

_cosmos_client: CosmosClient | None = None
_blob_client: BlobServiceClient | None = None

def get_cosmos_client() -> CosmosClient:
    global _cosmos_client
    if _cosmos_client is None:
        settings = get_settings()
        # connection_verify=False is required for local emulator's self-signed cert
        is_local = settings.cosmos_endpoint.startswith("https://localhost") or settings.cosmos_endpoint.startswith("https://127.0.0.1")
        
        if is_local:
            _cosmos_client = CosmosClient(
                url=settings.cosmos_endpoint,
                credential=settings.cosmos_key,
                connection_verify=False
            )
        else:
            from src.core.security import get_credential
            _cosmos_client = CosmosClient(
                url=settings.cosmos_endpoint,
                credential=get_credential()
            )
    return _cosmos_client

def get_invoices_container():
    client = get_cosmos_client()
    settings = get_settings()
    
    # We assume the database and container are already created by IaC.
    # We just fetch the client reference directly, which involves zero network I/O.
    database = client.get_database_client(settings.cosmos_database)
    container = database.get_container_client(settings.cosmos_container_invoices)
    
    return container

def get_blob_service_client() -> BlobServiceClient:
    global _blob_client
    if _blob_client is None:
        settings = get_settings()
        conn_str = settings.azure_storage_connection_string
        if conn_str.startswith("http"):
            from src.core.security import get_credential
            _blob_client = BlobServiceClient(account_url=conn_str, credential=get_credential())
        else:
            _blob_client = BlobServiceClient.from_connection_string(conn_str)
    return _blob_client

def get_raw_invoices_container():
    client = get_blob_service_client()
    settings = get_settings()
    
    # Just get the client reference without checking exists() to save a network roundtrip.
    container_client = client.get_container_client(settings.blob_container_raw_invoices)
    return container_client
