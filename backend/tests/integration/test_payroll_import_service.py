import io
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from app.core.config import get_settings
from app.core.exceptions import (
    DuplicateDocumentError,
    GeneralReaderUnavailableError,
    PayrollImportStateConflictError,
)
from app.integrations.general_reader.schemas import ExtractionResultV1
from app.models.enums import PayrollImportFieldReviewStatus, PayrollImportStatus
from app.models.organization import Organization
from app.models.payroll import PayrollVersion
from app.models.payroll_import import PayrollImport
from app.models.user import User
from app.services.auth.authentication import AuthenticatedUser
from app.services.imports.payroll_import_service import PayrollImportService
from app.storage.document_storage import LocalDocumentStorage

PNG = b"\x89PNG\r\n\x1a\n" + b"service-test-document"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "general_reader_extraction_v1.json"


def upload(filename: str = "generic.png") -> UploadFile:
    return UploadFile(
        io.BytesIO(PNG), filename=filename,
        headers=Headers({"content-type": "image/png"}),
    )


async def create_user(session: AsyncSession, label: str = "main") -> AuthenticatedUser:
    def work(sync: Session) -> AuthenticatedUser:
        organization = Organization(
            id=uuid4(), name=f"Import {label}", code=f"IMP-{uuid4().hex[:8]}",
            timezone="Europe/Istanbul", is_active=True,
        )
        user = User(
            id=uuid4(), organization_id=organization.id,
            email=f"{label}-{uuid4().hex}@test.invalid",
            password_hash="unused", is_active=True,
        )
        sync.add_all([organization, user])
        sync.flush()
        return AuthenticatedUser(
            id=user.id, organization_id=organization.id,
            roles=frozenset(), employee_id=None,
        )
    return await session.run_sync(work)


class FakeReader:
    def __init__(self, *, clean: bool = False,
                 failure: Exception | None = None) -> None:
        self.clean = clean
        self.failure = failure
        self.calls = []

    async def extract(self, document, **kwargs):
        self.calls.append({**kwargs, "content": document.read()})
        if self.failure:
            raise self.failure
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["request_id"] = kwargs["request_id"]
        payload["correlation_id"] = kwargs["request_id"]
        payload["tenant_context"]["tenant_id"] = str(kwargs["organization_id"])
        payload["document"]["sha256"] = kwargs["content_sha256"]
        payload["document"]["original_filename"] = kwargs["filename"]
        if self.clean:
            payload["fields"] = payload["fields"][:1]
            payload["missing_fields"] = []
            payload["tables"] = []
            payload["warnings"] = []
        return ExtractionResultV1.model_validate(payload)


def service(session: AsyncSession, tmp_path: Path,
            reader: FakeReader) -> PayrollImportService:
    settings = get_settings().model_copy(update={
        "payroll_document_max_upload_bytes": 1024,
        "general_reader_allow_llm": False,
    })
    return PayrollImportService(
        session, LocalDocumentStorage(tmp_path), reader, settings
    )


@pytest.mark.asyncio
async def test_upload_then_process_persists_metadata_and_honest_staging(
    async_db_session: AsyncSession, tmp_path: Path
):
    user = await create_user(async_db_session)
    reader = FakeReader()
    subject = service(async_db_session, tmp_path, reader)
    before_versions = await async_db_session.scalar(
        select(func.count()).select_from(PayrollVersion)
    )

    created = await subject.create(user, upload())
    assert created.status == PayrollImportStatus.UPLOADED
    assert created.processing_attempt == 0
    assert created.document.original_filename == "generic.png"
    assert not hasattr(created.document, "storage_key")

    processed = await subject.process(user, created.id)
    assert processed.status == PayrollImportStatus.REVIEW_REQUIRED
    assert processed.processing_attempt == 1
    assert processed.extraction_schema_version == "1.0"
    assert processed.template_external_id == "7"
    assert processed.template_version == 3
    assert processed.template_scope == "PRIVATE_TENANT"
    assert processed.template_match_score == pytest.approx(0.875)
    assert processed.document.reader_document_id == "41"
    assert processed.document.page_count == 1
    assert processed.reader_table_count == 1
    assert "TABLE_STAGING_DEFERRED" in processed.reader_warning_codes

    fields = await subject.fields(user, created.id)
    assert fields.count == 3
    statuses = {field.source_field_id: field.review_status for field in fields.items}
    assert statuses == {
        "field-a": PayrollImportFieldReviewStatus.UNREVIEWED,
        "field-b": PayrollImportFieldReviewStatus.MISSING,
        "field-c": PayrollImportFieldReviewStatus.MISSING,
    }
    field_a = next(value for value in fields.items if value.source_field_id == "field-a")
    assert field_a.raw_value == "123"
    assert field_a.normalized_value == "123"
    assert field_a.bbox == ["0.1", "0.2", "0.3", "0.4"]
    assert not hasattr(field_a, "canonical_key")
    assert reader.calls[0]["organization_id"] == user.organization_id
    assert reader.calls[0]["content"] == PNG
    assert get_settings().general_reader_allow_llm is False
    after_versions = await async_db_session.scalar(
        select(func.count()).select_from(PayrollVersion)
    )
    assert after_versions == before_versions


@pytest.mark.asyncio
async def test_clean_extraction_reaches_extracted_without_verification(
    async_db_session: AsyncSession, tmp_path: Path
):
    user = await create_user(async_db_session, "clean")
    subject = service(async_db_session, tmp_path, FakeReader(clean=True))
    created = await subject.create(user, upload())
    processed = await subject.process(user, created.id)
    assert processed.status == PayrollImportStatus.EXTRACTED
    fields = await subject.fields(user, created.id)
    assert [value.review_status for value in fields.items] == [
        PayrollImportFieldReviewStatus.UNREVIEWED
    ]


@pytest.mark.asyncio
async def test_reader_failure_is_durable_retains_file_and_retry_succeeds(
    async_db_session: AsyncSession, tmp_path: Path
):
    user = await create_user(async_db_session, "retry")
    reader = FakeReader(failure=GeneralReaderUnavailableError())
    subject = service(async_db_session, tmp_path, reader)
    created = await subject.create(user, upload())

    with pytest.raises(GeneralReaderUnavailableError):
        await subject.process(user, created.id)
    failed = await subject.get(user, created.id)
    assert failed.status == PayrollImportStatus.FAILED
    assert failed.processing_attempt == 1
    assert failed.last_error_code == "GENERAL_READER_UNAVAILABLE"
    assert failed.last_error_message == "The document extraction service is unavailable"
    assert LocalDocumentStorage(tmp_path).stat(
        (await _storage_key(async_db_session, user.organization_id, created.id))
    ).size_bytes == len(PNG)

    reader.failure = None
    retried = await subject.process(user, created.id)
    assert retried.status == PayrollImportStatus.REVIEW_REQUIRED
    assert retried.processing_attempt == 2
    assert retried.last_error_code is None


async def _storage_key(session: AsyncSession, organization_id, import_id) -> str:
    def work(sync: Session) -> str:
        item = sync.execute(select(PayrollImport).where(
            PayrollImport.id == import_id,
            PayrollImport.organization_id == organization_id,
        )).scalar_one()
        return item.documents[0].storage_key
    return await session.run_sync(work)


@pytest.mark.asyncio
async def test_duplicate_same_org_rejected_but_cross_org_same_hash_allowed(
    async_db_session: AsyncSession, tmp_path: Path
):
    first_user = await create_user(async_db_session, "dup-one")
    second_user = await create_user(async_db_session, "dup-two")
    reader = FakeReader()
    subject = service(async_db_session, tmp_path, reader)
    first = await subject.create(first_user, upload("one.png"))
    with pytest.raises(DuplicateDocumentError):
        await subject.create(first_user, upload("renamed.png"))
    second = await subject.create(second_user, upload("same.png"))
    assert first.content_sha256 == second.content_sha256
    assert first.id != second.id
    assert (await subject.list(first_user)).count == 1
    assert (await subject.list(second_user)).count == 1


@pytest.mark.asyncio
async def test_final_import_cannot_be_processed_again(
    async_db_session: AsyncSession, tmp_path: Path
):
    user = await create_user(async_db_session, "conflict")
    subject = service(async_db_session, tmp_path, FakeReader(clean=True))
    created = await subject.create(user, upload())
    await subject.process(user, created.id)
    with pytest.raises(PayrollImportStateConflictError):
        await subject.process(user, created.id)


@pytest.mark.asyncio
async def test_cross_org_get_list_and_fields_are_non_disclosing(
    async_db_session: AsyncSession, tmp_path: Path
):
    owner = await create_user(async_db_session, "owner")
    outsider = await create_user(async_db_session, "outsider")
    subject = service(async_db_session, tmp_path, FakeReader())
    created = await subject.create(owner, upload())
    assert (await subject.list(outsider)).count == 0
    from app.core.exceptions import PayrollImportNotFoundError
    with pytest.raises(PayrollImportNotFoundError):
        await subject.get(outsider, created.id)
    with pytest.raises(PayrollImportNotFoundError):
        await subject.fields(outsider, created.id)
