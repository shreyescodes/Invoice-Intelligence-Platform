"""Original invoice documents live in object storage, addressed by an opaque key."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Protocol

from app.config import Settings

_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_.\-]{0,400}$")


class DocumentNotFoundError(LookupError):
    pass


class DocumentStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def ping(self) -> None: ...


def _validate_key(key: str) -> str:
    if not _SAFE_KEY.match(key) or ".." in key:
        raise ValueError(f"invalid storage key: {key!r}")
    return key


class LocalDocumentStore:
    """Filesystem storage for development and single-node deployments."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / _validate_key(key)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"invalid storage key: {key!r}")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)  # atomic on POSIX and Windows

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise DocumentNotFoundError(key) from exc

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def ping(self) -> None:
        if not os.access(self.root, os.W_OK):
            raise OSError(f"document store {self.root} is not writable")


class AzureBlobDocumentStore:
    """Azure Blob Storage. Uses managed identity unless a connection string (e.g. Azurite) is given."""

    def __init__(self, settings: Settings) -> None:
        from azure.storage.blob import BlobServiceClient

        if settings.azure_storage_connection_string:
            service = BlobServiceClient.from_connection_string(
                settings.azure_storage_connection_string.get_secret_value()
            )
        elif settings.azure_storage_account_url:
            from azure.identity import DefaultAzureCredential

            service = BlobServiceClient(settings.azure_storage_account_url, credential=DefaultAzureCredential())
        else:
            raise ValueError("AZURE_STORAGE_ACCOUNT_URL or AZURE_STORAGE_CONNECTION_STRING is required")
        self._container = service.get_container_client(settings.azure_storage_container)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        from azure.storage.blob import ContentSettings

        self._container.upload_blob(
            _validate_key(key), data, overwrite=True, content_settings=ContentSettings(content_type=content_type)
        )

    def get(self, key: str) -> bytes:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return bytes(self._container.download_blob(_validate_key(key)).readall())
        except ResourceNotFoundError as exc:
            raise DocumentNotFoundError(key) from exc

    def delete(self, key: str) -> None:
        self._container.delete_blob(_validate_key(key), delete_snapshots="include")

    def ping(self) -> None:
        self._container.get_container_properties()


def build_document_store(settings: Settings) -> DocumentStore:
    if settings.storage_backend == "azure_blob":
        return AzureBlobDocumentStore(settings)
    return LocalDocumentStore(settings.storage_local_path)
