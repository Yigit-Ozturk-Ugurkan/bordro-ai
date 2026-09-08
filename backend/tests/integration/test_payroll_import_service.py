import io
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import UploadFile
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from app.core.config import get_settings
from app.core.exceptions import (
    DuplicateDocumentError,
    GeneralReaderContractInvalidError,
    GeneralReaderUnavailableError,
    PayrollImportStateConflictError,
)
from app.integrations.general_reader.schemas import ExtractionResultV1
from app.models.enums import PayrollImportFieldReviewStatus, PayrollImportStatus
from app.models.organization import Organization
from app.models.payroll import PayrollVersion
from app.models.payroll_import import (
    PayrollImport,
    PayrollImportTable,
    PayrollImportTableRow,
)
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
        self.payload = None

    async def extract(self, document, **kwargs):
        self.calls.append({**kwargs, "content": document.read()})
        if self.failure:
            raise self.failure
        payload = deepcopy(self.payload) if self.payload is not None else json.loads(
            FIXTURE.read_text(encoding="utf-8")
        )
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


def rich_table_payload() -> dict:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    table = payload["tables"][0]
    table["columns"] = [
        {"column_id": "description", "source_label": "Description", "value_type": "text"},
        {"column_id": "rate", "source_label": "Rate", "value_type": "text"},
        {"column_id": "amount", "source_label": "Amount", "value_type": "text"},
    ]
    table["rows"] = [{
        "row_index": 0,
        "page_number": 1,
        "bbox": [0.1, 0.2, 0.9, 0.3],
        "coordinate_space": "normalized_xyxy",
        "extraction_source": "rule",
        "cells": [{
            "column_id": "description",
            "source_label": "Description",
            "raw_value": "Normal Çalışma Kazancı",
            "normalized_value": "Normal Çalışma Kazancı",
            "value_type": "text",
            "confidence": 0.97,
            "bbox": [0.1, 0.2, 0.5, 0.3],
            "coordinate_space": "normalized_xyxy",
            "extraction_source": "rule",
        }, {
            "column_id": "rate",
            "source_label": "Rate",
            "raw_value": "1,00%",
            "normalized_value": "0.01",
            "value_type": "percentage",
            "confidence": 0.83,
            "bbox": None,
            "coordinate_space": "normalized_xyxy",
            "extraction_source": "rule",
        }, {
            "column_id": "amount",
            "source_label": "Amount",
            "raw_value": "14.000,00-",
            "normalized_value": "-14000.00",
            "value_type": "number",
            "confidence": 0.91,
            "bbox": [0.7, 0.2, 0.9, 0.3],
            "coordinate_space": "normalized_xyxy",
            "extraction_source": "rule",
        }],
    }, {
        "row_index": 1,
        "page_number": 1,
        "bbox": None,
        "coordinate_space": "normalized_xyxy",
        "extraction_source": "rule",
        "cells": [{
            "column_id": "description",
            "source_label": "Description",
            "raw_value": "Empty source position",
            "normalized_value": "Empty source position",
            "value_type": "text",
            "confidence": None,
            "bbox": None,
            "coordinate_space": "normalized_xyxy",
            "extraction_source": "rule",
        }, {
            "column_id": "amount",
            "source_label": "Amount",
            "raw_value": None,
            "normalized_value": None,
            "value_type": "number",
            "confidence": None,
            "bbox": None,
            "coordinate_space": "normalized_xyxy",
            "extraction_source": "rule",
        }],
    }]
    return payload


async def force_retryable(
    session: AsyncSession, organization_id, import_id,
) -> None:
    def work(sync: Session) -> None:
        item = sync.execute(select(PayrollImport).where(
            PayrollImport.id == import_id,
            PayrollImport.organization_id == organization_id,
        )).scalar_one()
        item.status = PayrollImportStatus.FAILED
        sync.flush()
    await session.run_sync(work)
    await session.commit()


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
    assert "TABLE_STAGING_DEFERRED" not in processed.reader_warning_codes
    assert "TABLE_CELL_CONFIDENCE_UNAVAILABLE" in processed.reader_warning_codes

    tables = await subject.tables(user, created.id)
    assert tables.count == 1
    detail = await subject.table(user, created.id, tables.items[0].id)
    assert detail.rows[0].cells[0].raw_value == "value"

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
    assert (await subject.tables(user, created.id)).count == 0


@pytest.mark.asyncio
async def test_scalar_and_rich_table_evidence_stage_from_one_extraction(
    async_db_session: AsyncSession, tmp_path: Path
):
    user = await create_user(async_db_session, "rich-table")
    reader = FakeReader()
    reader.payload = rich_table_payload()
    subject = service(async_db_session, tmp_path, reader)
    protected_tables = (
        "payroll_import_reviews",
        "payroll_import_field_corrections",
        "payroll_import_review_snapshots",
        "payroll_import_review_snapshot_fields",
        "payroll_import_validation_runs",
        "payroll_import_validation_results",
        "payroll_import_approvals",
        "payroll_import_validation_acknowledgements",
        "payroll_import_materializations",
        "payroll_versions",
        "payroll_earnings",
        "payroll_deductions",
        "payroll_absences",
        "tax_calculation_runs",
        "tax_cumulative_records",
        "payroll_tax_ledger_syncs",
        "payroll_tax_ledger_rebuilds",
        "payroll_tax_ledger_rebuild_items",
    )
    before = {
        name: await async_db_session.scalar(text(f"SELECT count(*) FROM {name}"))
        for name in protected_tables
    }

    created = await subject.create(user, upload("rich.png"))
    processed = await subject.process(user, created.id)
    assert processed.reader_table_count == 1
    assert len(reader.calls) == 1
    assert (await subject.fields(user, created.id)).count == 3
    listing = await subject.tables(user, created.id)
    assert listing.count == 1
    detail = await subject.table(user, created.id, listing.items[0].id)
    assert detail.source_table_index == 0
    assert detail.page_numbers == [1]
    assert detail.row_count == 2
    assert detail.column_count == 3
    assert len(detail.source_checksum) == 64
    stored_table = await async_db_session.scalar(select(PayrollImportTable).where(
        PayrollImportTable.id == detail.id,
    ))
    assert stored_table is not None
    assert stored_table.organization_id == user.organization_id
    assert stored_table.payroll_import_id == created.id
    assert stored_table.payroll_import_document_id == created.document.id
    assert stored_table.source_columns[0] == {
        "column_index": 0,
        "source_column_id": "description",
        "source_label": "Description",
        "value_type": "text",
    }
    assert [row.row_index for row in detail.rows] == [0, 1]
    assert [cell.column_index for cell in detail.rows[0].cells] == [0, 1, 2]
    assert detail.rows[0].cells[0].raw_value == "Normal Çalışma Kazancı"
    assert detail.rows[0].cells[1].raw_value == "1,00%"
    assert detail.rows[0].cells[2].raw_value == "14.000,00-"
    assert detail.rows[0].cells[2].confidence == Decimal("0.91000000")
    assert detail.rows[0].cells[2].bbox == ["0.7", "0.2", "0.9", "0.3"]
    empty = detail.rows[1].cells[1]
    assert empty.column_index == 2
    assert empty.raw_value is None
    assert empty.raw_value != "0"
    after = {
        name: await async_db_session.scalar(text(f"SELECT count(*) FROM {name}"))
        for name in protected_tables
    }
    assert after == before


@pytest.mark.asyncio
async def test_multiple_tables_stay_separate_and_source_ordered(
    async_db_session: AsyncSession, tmp_path: Path
):
    user = await create_user(async_db_session, "multiple-tables")
    payload = rich_table_payload()
    payload["document"]["page_count"] = 2
    payload["document"]["internal_document_ids"].append(42)
    second_page = deepcopy(payload["pages"][0])
    second_page["page_number"] = 2
    second_page["internal_document_id"] = 42
    payload["pages"].append(second_page)
    payload["tables"][0]["page_numbers"] = [1, 2]
    payload["tables"][0]["rows"][1]["page_number"] = 2
    second = deepcopy(payload["tables"][0])
    second["table_id"] = "second-table"
    second["source_label"] = "Second Table"
    second["rows"] = second["rows"][:1]
    second["page_numbers"] = [1]
    payload["tables"].append(second)
    reader = FakeReader()
    reader.payload = payload
    subject = service(async_db_session, tmp_path, reader)
    created = await subject.create(user, upload("multiple.png"))
    await subject.process(user, created.id)
    listing = await subject.tables(user, created.id)
    assert [item.source_table_index for item in listing.items] == [0, 1]
    assert [item.source_table_id for item in listing.items] == [
        "generic-table", "second-table",
    ]
    first = await subject.table(user, created.id, listing.items[0].id)
    second_result = await subject.table(user, created.id, listing.items[1].id)
    assert first.page_numbers == [1, 2]
    assert [row.page_number for row in first.rows] == [1, 2]
    assert second_result.page_numbers == [1]
    assert first.rows[0].cells[0].raw_value == "Normal Çalışma Kazancı"
    assert second_result.rows[0].cells[0].raw_value == "Normal Çalışma Kazancı"
    assert first.id != second_result.id


@pytest.mark.asyncio
async def test_retry_replaces_equivalent_then_changed_machine_table_staging(
    async_db_session: AsyncSession, tmp_path: Path
):
    user = await create_user(async_db_session, "replace-tables")
    reader = FakeReader()
    reader.payload = rich_table_payload()
    subject = service(async_db_session, tmp_path, reader)
    created = await subject.create(user, upload("replace.png"))
    await subject.process(user, created.id)
    first_list = await subject.tables(user, created.id)
    first_checksum = first_list.items[0].source_checksum

    equivalent_payload = rich_table_payload()
    equivalent_payload["tables"][0]["rows"].reverse()
    for source_row in equivalent_payload["tables"][0]["rows"]:
        source_row["cells"].reverse()
    reader.payload = equivalent_payload
    await force_retryable(async_db_session, user.organization_id, created.id)
    await subject.process(user, created.id)
    equivalent = await subject.tables(user, created.id)
    equivalent_detail = await subject.table(
        user, created.id, equivalent.items[0].id,
    )
    assert equivalent.count == 1
    assert equivalent.items[0].source_checksum == first_checksum
    assert sum(len(row.cells) for row in equivalent_detail.rows) == 5

    changed = rich_table_payload()
    changed["tables"][0]["rows"][0]["cells"][2]["raw_value"] = "15.000,00-"
    reader.payload = changed
    await force_retryable(async_db_session, user.organization_id, created.id)
    await subject.process(user, created.id)
    latest = await subject.tables(user, created.id)
    latest_detail = await subject.table(user, created.id, latest.items[0].id)
    assert latest.count == 1
    assert sum(len(row.cells) for row in latest_detail.rows) == 5
    assert latest.items[0].source_checksum != first_checksum
    assert latest_detail.rows[0].cells[2].raw_value == "15.000,00-"


@pytest.mark.asyncio
async def test_malformed_table_fails_atomically_and_preserves_prior_staging(
    async_db_session: AsyncSession, tmp_path: Path
):
    user = await create_user(async_db_session, "malformed-table")
    reader = FakeReader()
    reader.payload = rich_table_payload()
    subject = service(async_db_session, tmp_path, reader)
    created = await subject.create(user, upload("malformed.png"))
    await subject.process(user, created.id)
    first_tables = await subject.tables(user, created.id)
    first_checksum = first_tables.items[0].source_checksum
    first_fields = await subject.fields(user, created.id)

    malformed = rich_table_payload()
    malformed["fields"][0]["raw_value"] = "changed scalar"
    duplicate = deepcopy(malformed["tables"][0]["rows"][0]["cells"][0])
    malformed["tables"][0]["rows"][0]["cells"].append(duplicate)
    reader.payload = malformed
    await force_retryable(async_db_session, user.organization_id, created.id)
    with pytest.raises(GeneralReaderContractInvalidError):
        await subject.process(user, created.id)

    failed = await subject.get(user, created.id)
    assert failed.status == PayrollImportStatus.FAILED
    assert failed.last_error_code == "GENERAL_READER_CONTRACT_INVALID"
    current_tables = await subject.tables(user, created.id)
    current_fields = await subject.fields(user, created.id)
    assert current_tables.count == 1
    assert current_tables.items[0].source_checksum == first_checksum
    assert [field.raw_value for field in current_fields.items] == [
        field.raw_value for field in first_fields.items
    ]


@pytest.mark.asyncio
async def test_table_limits_fail_closed_without_partial_scalar_staging(
    async_db_session: AsyncSession, tmp_path: Path
):
    user = await create_user(async_db_session, "table-limit")
    payload = rich_table_payload()
    payload["tables"].append(deepcopy(payload["tables"][0]))
    payload["tables"][1]["table_id"] = "too-many"
    reader = FakeReader()
    reader.payload = payload
    settings = get_settings().model_copy(update={"payroll_import_max_tables": 1})
    subject = PayrollImportService(
        async_db_session, LocalDocumentStorage(tmp_path), reader, settings,
    )
    created = await subject.create(user, upload("limited.png"))
    with pytest.raises(GeneralReaderContractInvalidError):
        await subject.process(user, created.id)
    assert (await subject.fields(user, created.id)).count == 0
    assert (await subject.tables(user, created.id)).count == 0


@pytest.mark.asyncio
async def test_raw_cell_text_limit_fails_closed(
    async_db_session: AsyncSession, tmp_path: Path
):
    user = await create_user(async_db_session, "cell-limit")
    reader = FakeReader()
    reader.payload = rich_table_payload()
    settings = get_settings().model_copy(update={
        "payroll_import_max_cell_value_chars": 5,
    })
    subject = PayrollImportService(
        async_db_session, LocalDocumentStorage(tmp_path), reader, settings,
    )
    created = await subject.create(user, upload("cell-limited.png"))
    with pytest.raises(GeneralReaderContractInvalidError):
        await subject.process(user, created.id)
    assert (await subject.fields(user, created.id)).count == 0
    assert (await subject.tables(user, created.id)).count == 0


@pytest.mark.asyncio
async def test_table_row_database_fk_rejects_cross_organization_attachment(
    async_db_session: AsyncSession, tmp_path: Path
):
    owner = await create_user(async_db_session, "table-owner")
    outsider = await create_user(async_db_session, "table-outsider")
    reader = FakeReader()
    reader.payload = rich_table_payload()
    subject = service(async_db_session, tmp_path, reader)
    created = await subject.create(owner, upload("owner-table.png"))
    await subject.process(owner, created.id)
    table_id = (await subject.tables(owner, created.id)).items[0].id

    with pytest.raises(IntegrityError):
        async with async_db_session.begin_nested():
            async_db_session.add(PayrollImportTableRow(
                organization_id=outsider.organization_id,
                table_id=table_id,
                row_index=99,
                page_number=1,
                coordinate_space="normalized_xyxy",
                extraction_source="test",
            ))
            await async_db_session.flush()


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
async def test_approved_evidence_cannot_be_reprocessed_or_mutated(
    async_db_session: AsyncSession, tmp_path: Path
):
    from tests.integration.test_payroll_approval import (
        authoritative_counts,
        immutable_upstream_state,
        immutable_validation_state,
    )
    from tests.integration.test_payroll_materialization import (
        approval_evidence_state,
        approved_evidence,
    )

    user, import_id, snapshot, run, _approval = await approved_evidence(
        async_db_session,
    )
    before_authoritative = await async_db_session.run_sync(authoritative_counts)
    before_upstream = await async_db_session.run_sync(
        lambda sync: immutable_upstream_state(sync, import_id, snapshot.id)
    )
    before_validation = await async_db_session.run_sync(
        lambda sync: immutable_validation_state(sync, run.id)
    )
    before_approval = await async_db_session.run_sync(
        lambda sync: approval_evidence_state(sync, import_id)
    )
    reader = FakeReader()
    subject = service(async_db_session, tmp_path, reader)

    with pytest.raises(PayrollImportStateConflictError):
        await subject.process(user, import_id)

    assert reader.calls == []
    assert await async_db_session.run_sync(authoritative_counts) == before_authoritative
    assert await async_db_session.run_sync(
        lambda sync: immutable_upstream_state(sync, import_id, snapshot.id)
    ) == before_upstream
    assert await async_db_session.run_sync(
        lambda sync: immutable_validation_state(sync, run.id)
    ) == before_validation
    assert await async_db_session.run_sync(
        lambda sync: approval_evidence_state(sync, import_id)
    ) == before_approval


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
