"""Protected document storage abstractions."""

from app.storage.document_storage import (
    DocumentStorage,
    LocalDocumentStorage,
    StoredDocument,
)

__all__ = ["DocumentStorage", "LocalDocumentStorage", "StoredDocument"]
