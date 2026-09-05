import hashlib
import os
from pathlib import Path

import pytest

from app.core.exceptions import (
    DocumentTooLargeError,
    DocumentUploadError,
    ImportProcessingFailedError,
    UnsupportedDocumentTypeError,
)
from app.storage.document_storage import LocalDocumentStorage

PNG = b"\x89PNG\r\n\x1a\n" + b"generic-test-bytes"


class Stream:
    def __init__(self, value: bytes) -> None:
        self.value = value
        self.offset = 0

    async def read(self, size: int = -1) -> bytes:
        if self.offset >= len(self.value):
            return b""
        end = len(self.value) if size < 0 else self.offset + size
        chunk = self.value[self.offset:end]
        self.offset += len(chunk)
        return chunk


@pytest.mark.asyncio
async def test_local_storage_uses_opaque_key_and_exact_metadata(tmp_path: Path):
    storage = LocalDocumentStorage(tmp_path)
    stored = await storage.put(
        Stream(PNG), original_filename="C:\\client\\..\\payroll.png",
        declared_mime_type="image/png", max_bytes=1024,
    )
    assert stored.original_filename == "payroll.png"
    assert "payroll" not in stored.storage_key
    assert stored.size_bytes == len(PNG)
    assert stored.sha256 == hashlib.sha256(PNG).hexdigest()
    assert stored.detected_mime_type == "image/png"
    with storage.open(stored.storage_key) as handle:
        assert handle.read() == PNG
    assert storage.stat(stored.storage_key).size_bytes == len(PNG)
    assert not Path(stored.storage_key).is_absolute()


@pytest.mark.asyncio
async def test_same_content_has_same_hash_but_distinct_opaque_keys(tmp_path: Path):
    storage = LocalDocumentStorage(tmp_path)
    first = await storage.put(Stream(PNG), original_filename="one.png",
                              declared_mime_type="image/png", max_bytes=1024)
    second = await storage.put(Stream(PNG), original_filename="two.png",
                               declared_mime_type="image/png", max_bytes=1024)
    assert first.sha256 == second.sha256
    assert first.storage_key != second.storage_key


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "filename", "mime", "error"),
    [
        (b"", "empty.png", "image/png", DocumentUploadError),
        (PNG, "bad.exe", "image/png", UnsupportedDocumentTypeError),
        (PNG, "bad.jpg", "image/jpeg", DocumentUploadError),
        (PNG, "bad.png", "image/jpeg", DocumentUploadError),
        (b"not-magic", "bad.png", "image/png", DocumentUploadError),
    ],
)
async def test_ingress_validation_rejects_invalid_uploads(
    tmp_path: Path, value: bytes, filename: str, mime: str, error: type[Exception]
):
    storage = LocalDocumentStorage(tmp_path)
    with pytest.raises(error):
        await storage.put(Stream(value), original_filename=filename,
                          declared_mime_type=mime, max_bytes=1024)


@pytest.mark.asyncio
async def test_oversized_upload_rejected_and_temp_cleaned(tmp_path: Path):
    storage = LocalDocumentStorage(tmp_path)
    with pytest.raises(DocumentTooLargeError):
        await storage.put(Stream(PNG), original_filename="large.png",
                          declared_mime_type="image/png", max_bytes=len(PNG) - 1)
    assert list((tmp_path / ".tmp").iterdir()) == []


@pytest.mark.asyncio
async def test_failed_atomic_rename_cleans_temporary_file(tmp_path: Path, monkeypatch):
    storage = LocalDocumentStorage(tmp_path)

    def fail_replace(_source, _target):
        raise OSError("sensitive filesystem path")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(ImportProcessingFailedError) as caught:
        await storage.put(Stream(PNG), original_filename="valid.png",
                          declared_mime_type="image/png", max_bytes=1024)
    assert "sensitive" not in str(caught.value)
    assert list((tmp_path / ".tmp").iterdir()) == []


@pytest.mark.asyncio
async def test_delete_removes_only_resolved_storage_key(tmp_path: Path):
    storage = LocalDocumentStorage(tmp_path)
    stored = await storage.put(Stream(PNG), original_filename="valid.png",
                               declared_mime_type="image/png", max_bytes=1024)
    storage.delete(stored.storage_key)
    with pytest.raises(ImportProcessingFailedError):
        storage.open(stored.storage_key)
    with pytest.raises(ImportProcessingFailedError):
        storage.open("../outside")


def test_repository_and_frontend_storage_roots_are_rejected():
    backend_root = Path(__file__).resolve().parents[2]
    with pytest.raises(ImportProcessingFailedError):
        LocalDocumentStorage(backend_root)
    with pytest.raises(ImportProcessingFailedError):
        LocalDocumentStorage(backend_root.parent / "frontend" / "public")
