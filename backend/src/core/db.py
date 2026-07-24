"""Database and Storage clients."""
import logging
from azure.cosmos import CosmosClient, PartitionKey
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
        
        _cosmos_client = CosmosClient(
            url=settings.cosmos_endpoint,
            credential=settings.cosmos_key,
            connection_verify=not is_local
        )
    return _cosmos_client

def get_invoices_container():
    client = get_cosmos_client()
    settings = get_settings()
    
    database = client.create_database_if_not_exists(id=settings.cosmos_database)
    
    container = database.create_container_if_not_exists(
        id=settings.cosmos_container_invoices,
        partition_key=PartitionKey(path="/vendor_id"),
        offer_throughput=400
    )
    return container

def get_blob_service_client() -> BlobServiceClient:
    global _blob_client
    if _blob_client is None:
        settings = get_settings()
        _blob_client = BlobServiceClient.from_connection_string(
            settings.azure_storage_connection_string
        )
    return _blob_client

def get_raw_invoices_container():
    client = get_blob_service_client()
    settings = get_settings()
    
    container_client = client.get_container_client(settings.blob_container_raw_invoices)
    if not container_client.exists():
        container_client.create_container()
    return container_client
