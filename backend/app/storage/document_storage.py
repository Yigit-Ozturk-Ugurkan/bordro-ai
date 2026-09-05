"""Bordro-owned storage for authoritative uploaded source documents."""

from __future__ import annotations

import hashlib
import os
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import UUID, uuid4

from app.core.exceptions import (
    DocumentTooLargeError,
    DocumentUploadError,
    ImportProcessingFailedError,
    UnsupportedDocumentTypeError,
)


class AsyncReadable(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True)
class StoredDocument:
    file_id: UUID
    storage_key: str
    original_filename: str
    declared_mime_type: str
    detected_mime_type: str
    size_bytes: int
    sha256: str
    storage_provider: str = "LOCAL"


@dataclass(frozen=True)
class StoredDocumentStat:
    size_bytes: int


@dataclass(frozen=True)
class DocumentType:
    extensions: frozenset[str]
    mime_types: frozenset[str]
    detected_mime_type: str


DOCUMENT_TYPES = {
    "pdf": DocumentType(frozenset({".pdf"}), frozenset({"application/pdf"}), "application/pdf"),
    "jpeg": DocumentType(frozenset({".jpg", ".jpeg"}), frozenset({"image/jpeg"}), "image/jpeg"),
    "png": DocumentType(frozenset({".png"}), frozenset({"image/png"}), "image/png"),
    "bmp": DocumentType(frozenset({".bmp"}), frozenset({"image/bmp", "image/x-ms-bmp"}), "image/bmp"),
    "tiff": DocumentType(frozenset({".tif", ".tiff"}), frozenset({"image/tiff"}), "image/tiff"),
    "webp": DocumentType(frozenset({".webp"}), frozenset({"image/webp"}), "image/webp"),
}


def safe_display_filename(filename: str) -> str:
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not name or len(name) > 255 or any(ord(character) < 32 for character in name):
        raise DocumentUploadError("The document filename is invalid")
    return name


def detect_document_type(header: bytes) -> DocumentType | None:
    if header.startswith(b"%PDF-"):
        return DOCUMENT_TYPES["pdf"]
    if header.startswith(b"\xff\xd8\xff"):
        return DOCUMENT_TYPES["jpeg"]
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return DOCUMENT_TYPES["png"]
    if header.startswith(b"BM"):
        return DOCUMENT_TYPES["bmp"]
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return DOCUMENT_TYPES["tiff"]
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return DOCUMENT_TYPES["webp"]
    return None


def validate_type(filename: str, declared_mime_type: str,
                  detected: DocumentType | None) -> DocumentType:
    extension = Path(filename).suffix.lower()
    supported = {suffix for item in DOCUMENT_TYPES.values() for suffix in item.extensions}
    if extension not in supported:
        raise UnsupportedDocumentTypeError()
    if detected is None or extension not in detected.extensions:
        raise DocumentUploadError("The document content does not match its extension")
    declared = (declared_mime_type or "").split(";", 1)[0].strip().lower()
    if declared not in detected.mime_types:
        raise DocumentUploadError("The declared MIME type does not match the document")
    return detected


class DocumentStorage(ABC):
    @abstractmethod
    async def put(self, stream: AsyncReadable, *, original_filename: str,
                  declared_mime_type: str, max_bytes: int) -> StoredDocument: ...

    @abstractmethod
    def open(self, storage_key: str) -> BinaryIO: ...

    @abstractmethod
    def stat(self, storage_key: str) -> StoredDocumentStat: ...

    @abstractmethod
    def delete(self, storage_key: str) -> None: ...


class LocalDocumentStorage(DocumentStorage):
    """Atomic local implementation; keys are opaque and root-confined."""

    def __init__(self, root: Path) -> None:
        backend_root = Path(__file__).resolve().parents[2]
        self.root = (root if root.is_absolute() else backend_root / root).resolve()
        project_root = backend_root.parent
        frontend_root = project_root / "frontend"
        if self.root in {backend_root, project_root}:
            raise ImportProcessingFailedError("The document storage root is unsafe")
        try:
            self.root.relative_to(frontend_root.resolve())
        except ValueError:
            pass
        else:
            raise ImportProcessingFailedError("The document storage root is unsafe")

    async def put(self, stream: AsyncReadable, *, original_filename: str,
                  declared_mime_type: str, max_bytes: int) -> StoredDocument:
        display_name = safe_display_filename(original_filename)
        self.root.mkdir(parents=True, exist_ok=True)
        temp_dir = self.root / ".tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        handle = None
        temp_path: Path | None = None
        try:
            handle = tempfile.NamedTemporaryFile(
                mode="w+b", prefix="upload-", suffix=".tmp",
                dir=temp_dir, delete=False,
            )
            temp_path = Path(handle.name)
            digest = hashlib.sha256()
            size = 0
            header = b""
            while True:
                chunk = await stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise DocumentTooLargeError()
                if len(header) < 16:
                    header = (header + chunk)[:16]
                digest.update(chunk)
                handle.write(chunk)
            if size == 0:
                raise DocumentUploadError("The document is empty")
            detected = validate_type(display_name, declared_mime_type,
                                     detect_document_type(header))
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            handle = None

            file_id = uuid4()
            storage_key = f"{file_id.hex[:2]}/{file_id.hex}"
            final_path = self._resolve_key(storage_key)
            final_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp_path, final_path)
            temp_path = None
            return StoredDocument(
                file_id=file_id,
                storage_key=storage_key,
                original_filename=display_name,
                declared_mime_type=(declared_mime_type or "").split(";", 1)[0].strip().lower(),
                detected_mime_type=detected.detected_mime_type,
                size_bytes=size,
                sha256=digest.hexdigest(),
            )
        except (DocumentUploadError, DocumentTooLargeError, UnsupportedDocumentTypeError):
            raise
        except Exception as exc:
            raise ImportProcessingFailedError("The document could not be stored") from exc
        finally:
            if handle is not None:
                handle.close()
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def open(self, storage_key: str) -> BinaryIO:
        try:
            return self._resolve_key(storage_key).open("rb")
        except OSError as exc:
            raise ImportProcessingFailedError("The stored document is unavailable") from exc

    def stat(self, storage_key: str) -> StoredDocumentStat:
        try:
            return StoredDocumentStat(size_bytes=self._resolve_key(storage_key).stat().st_size)
        except OSError as exc:
            raise ImportProcessingFailedError("The stored document is unavailable") from exc

    def delete(self, storage_key: str) -> None:
        try:
            self._resolve_key(storage_key).unlink(missing_ok=True)
        except OSError as exc:
            raise ImportProcessingFailedError("The stored document could not be deleted") from exc

    def _resolve_key(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ImportProcessingFailedError("The stored document key is invalid") from exc
        return candidate


__all__ = [
    "DOCUMENT_TYPES", "DocumentStorage", "LocalDocumentStorage", "StoredDocument",
    "StoredDocumentStat", "detect_document_type", "safe_display_filename",
]
