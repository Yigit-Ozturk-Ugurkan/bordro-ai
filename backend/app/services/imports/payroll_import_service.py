"""Durable V2.1A upload and explicit extraction orchestration."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    BordroError,
    DuplicateDocumentError,
    GeneralReaderContractInvalidError,
    ImportProcessingFailedError,
    PayrollImportNotFoundError,
    PayrollImportTableNotFoundError,
)
from app.integrations.general_reader.client import GeneralReaderClient
from app.integrations.general_reader.schemas import ExtractionResultV1, FieldV1, TableV1
from app.models.enums import PayrollImportFieldReviewStatus, PayrollImportStatus
from app.models.payroll_import import (
    PayrollImport,
    PayrollImportDocument,
    PayrollImportField,
    PayrollImportTable,
    PayrollImportTableCell,
    PayrollImportTableRow,
)
from app.repositories.payroll_import_repository import PayrollImportRepository
from app.schemas.payroll_import import (
    PayrollImportDocumentRead,
    PayrollImportFieldList,
    PayrollImportList,
    PayrollImportListItem,
    PayrollImportRead,
    PayrollImportTableList,
    PayrollImportTableRead,
)
from app.services.auth.authentication import AuthenticatedUser
from app.services.imports.state_machine import transition
from app.storage.document_storage import DocumentStorage

logger = logging.getLogger(__name__)


class PayrollImportService:
    def __init__(self, session: AsyncSession, storage: DocumentStorage,
                 reader: GeneralReaderClient, settings: Settings | None = None) -> None:
        self._session = session
        self._storage = storage
        self._reader = reader
        self._settings = settings or get_settings()

    async def create(self, user: AuthenticatedUser,
                     upload: UploadFile) -> PayrollImportRead:
        stored = await self._storage.put(
            upload, original_filename=upload.filename or "",
            declared_mime_type=upload.content_type or "",
            max_bytes=self._settings.payroll_document_max_upload_bytes,
        )
        import_id = uuid4()
        document_id = uuid4()

        def work(sync_session: Session) -> PayrollImportRead:
            repository = PayrollImportRepository(sync_session)
            if repository.find_by_hash(user.organization_id, stored.sha256):
                raise DuplicateDocumentError()
            item = PayrollImport(
                id=import_id,
                organization_id=user.organization_id,
                uploaded_by_user_id=user.id,
                status=PayrollImportStatus.UPLOADED,
                source_type="DOCUMENT_UPLOAD",
                reader_provider="GENERAL_READER",
                source_document_id=document_id,
                content_sha256=stored.sha256,
                reader_table_count=0,
                reader_warnings=[],
                processing_attempt=0,
            )
            document = PayrollImportDocument(
                id=document_id,
                organization_id=user.organization_id,
                payroll_import_id=import_id,
                file_id=stored.file_id,
                original_filename=stored.original_filename,
                declared_mime_type=stored.declared_mime_type,
                detected_mime_type=stored.detected_mime_type,
                size_bytes=stored.size_bytes,
                sha256=stored.sha256,
                storage_provider=stored.storage_provider,
                storage_key=stored.storage_key,
            )
            repository.add(item, document)
            return self._detail(item, document)

        try:
            result = await self._session.run_sync(work)
            await self._session.commit()
            return result
        except DuplicateDocumentError:
            await self._session.rollback()
            self._delete_failed_upload(stored.storage_key, stored.file_id)
            raise
        except IntegrityError as exc:
            await self._session.rollback()
            self._delete_failed_upload(stored.storage_key, stored.file_id)
            diagnostic = getattr(getattr(exc, "orig", None), "diag", None)
            if getattr(diagnostic, "constraint_name", None) == (
                "uq_payroll_import_org_content_sha256"
            ):
                raise DuplicateDocumentError() from None
            raise ImportProcessingFailedError(
                "The payroll import could not be created"
            ) from exc
        except Exception as exc:
            await self._session.rollback()
            self._delete_failed_upload(stored.storage_key, stored.file_id)
            if isinstance(exc, BordroError):
                raise
            raise ImportProcessingFailedError("The payroll import could not be created") from exc

    def _delete_failed_upload(self, storage_key: str, file_id: UUID) -> None:
        try:
            self._storage.delete(storage_key)
        except BordroError:
            logger.warning("Failed upload cleanup requires attention file_id=%s", file_id)

    async def process(self, user: AuthenticatedUser,
                      import_id: UUID) -> PayrollImportRead:
        def start(sync_session: Session) -> tuple[str, str, str, str]:
            item = PayrollImportRepository(sync_session).get_for_update(
                user.organization_id, import_id
            )
            if item is None:
                raise PayrollImportNotFoundError()
            transition(item, PayrollImportStatus.PROCESSING)
            item.processing_attempt += 1
            item.processing_started_at = datetime.now(timezone.utc)
            item.processed_at = None
            item.last_error_code = None
            item.last_error_message = None
            document = self._source_document(item)
            sync_session.flush()
            return (
                document.storage_key, document.original_filename,
                document.detected_mime_type, item.content_sha256,
            )

        try:
            storage_key, filename, mime_type, content_sha256 = (
                await self._session.run_sync(start)
            )
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

        try:
            with self._storage.open(storage_key) as document_stream:
                extraction = await self._reader.extract(
                    document_stream,
                    filename=filename,
                    mime_type=mime_type,
                    content_sha256=content_sha256,
                    organization_id=user.organization_id,
                    request_id=str(import_id),
                )
            result = await self._persist_extraction(user.organization_id, import_id, extraction)
            await self._session.commit()
            logger.info("Payroll import processed import_id=%s organization_id=%s status=%s",
                        import_id, user.organization_id, result.status)
            return result
        except Exception as exc:
            await self._session.rollback()
            safe_error = exc if isinstance(exc, BordroError) else ImportProcessingFailedError()
            await self._mark_failed(user.organization_id, import_id, safe_error)
            if isinstance(exc, BordroError):
                raise
            raise safe_error from exc

    async def list(self, user: AuthenticatedUser) -> PayrollImportList:
        def work(sync_session: Session) -> PayrollImportList:
            repository = PayrollImportRepository(sync_session)
            items = []
            for item in repository.list(user.organization_id):
                loaded = repository.get(user.organization_id, item.id, load_documents=True)
                document = self._source_document(loaded)
                items.append(PayrollImportListItem(
                    id=item.id, status=item.status,
                    original_filename=document.original_filename,
                    size_bytes=document.size_bytes,
                    content_sha256=item.content_sha256,
                    processing_attempt=item.processing_attempt,
                    created_at=item.created_at, processed_at=item.processed_at,
                ))
            return PayrollImportList(count=len(items), items=items)
        return await self._session.run_sync(work)

    async def get(self, user: AuthenticatedUser,
                  import_id: UUID) -> PayrollImportRead:
        def work(sync_session: Session) -> PayrollImportRead:
            item = PayrollImportRepository(sync_session).get(
                user.organization_id, import_id, load_documents=True
            )
            if item is None:
                raise PayrollImportNotFoundError()
            return self._detail(item, self._source_document(item))
        return await self._session.run_sync(work)

    async def fields(self, user: AuthenticatedUser,
                     import_id: UUID) -> PayrollImportFieldList:
        def work(sync_session: Session) -> PayrollImportFieldList:
            repository = PayrollImportRepository(sync_session)
            if repository.get(user.organization_id, import_id) is None:
                raise PayrollImportNotFoundError()
            rows = repository.list_fields(user.organization_id, import_id)
            return PayrollImportFieldList(import_id=import_id, count=len(rows), items=rows)
        return await self._session.run_sync(work)

    async def tables(self, user: AuthenticatedUser,
                     import_id: UUID) -> PayrollImportTableList:
        def work(sync_session: Session) -> PayrollImportTableList:
            repository = PayrollImportRepository(sync_session)
            if repository.get(user.organization_id, import_id) is None:
                raise PayrollImportNotFoundError()
            rows = repository.list_tables(user.organization_id, import_id)
            return PayrollImportTableList(import_id=import_id, count=len(rows), items=rows)
        return await self._session.run_sync(work)

    async def table(self, user: AuthenticatedUser, import_id: UUID,
                    table_id: UUID) -> PayrollImportTableRead:
        def work(sync_session: Session) -> PayrollImportTableRead:
            repository = PayrollImportRepository(sync_session)
            if repository.get(user.organization_id, import_id) is None:
                raise PayrollImportNotFoundError()
            row = repository.get_table(user.organization_id, import_id, table_id)
            if row is None:
                raise PayrollImportTableNotFoundError()
            return PayrollImportTableRead.model_validate(row)
        return await self._session.run_sync(work)

    async def _persist_extraction(self, organization_id: UUID, import_id: UUID,
                                  result: ExtractionResultV1) -> PayrollImportRead:
        def work(sync_session: Session) -> PayrollImportRead:
            repository = PayrollImportRepository(sync_session)
            item = repository.get_for_update(organization_id, import_id)
            if item is None:
                raise PayrollImportNotFoundError()
            if item.status != PayrollImportStatus.PROCESSING:
                from app.core.exceptions import PayrollImportStateConflictError
                raise PayrollImportStateConflictError()
            document = self._source_document(item)
            document.reader_document_id = (
                str(result.document.internal_document_ids[0])
                if result.document.internal_document_ids else None
            )
            document.page_count = result.document.page_count
            item.extraction_schema_version = result.schema_version
            item.reader_table_count = len(result.tables)
            item.reader_warnings = [warning.model_dump(mode="json") for warning in result.warnings]
            template = max(
                result.templates,
                key=lambda candidate: candidate.match_score
                if candidate.match_score is not None else Decimal("-1"),
                default=None,
            )
            if template is not None:
                item.template_external_id = (
                    str(template.template_id) if template.template_id is not None else None
                )
                item.template_version = template.template_version
                item.template_scope = template.scope
                item.template_match_score = template.match_score

            missing = {
                (value.field_id, value.page_number): value
                for value in result.missing_fields
            }
            rows: list[PayrollImportField] = []
            represented: set[tuple[str, int]] = set()
            for source in result.fields:
                key = (source.field_id, source.page_number)
                represented.add(key)
                missing_value = missing.get(key)
                review_status = self._review_status(source, missing_value is not None)
                rows.append(PayrollImportField(
                    organization_id=organization_id,
                    payroll_import_id=import_id,
                    payroll_import_document_id=document.id,
                    source_field_id=source.field_id,
                    source_label=source.source_label,
                    source_text=source.source_text,
                    raw_value=source.raw_value,
                    normalized_value=source.normalized_value,
                    value_type=source.value_type,
                    confidence=source.confidence,
                    page_number=source.page_number,
                    bbox=[str(value) for value in source.bbox] if source.bbox else None,
                    coordinate_space=source.coordinate_space,
                    extraction_source=source.extraction_source,
                    rule_index=source.rule_index,
                    missing_reason_code=(missing_value.reason_code if missing_value else None),
                    missing_reason=(missing_value.safe_reason_text if missing_value else None),
                    review_status=review_status,
                ))
            for key, source in missing.items():
                if key in represented:
                    continue
                rows.append(PayrollImportField(
                    organization_id=organization_id,
                    payroll_import_id=import_id,
                    payroll_import_document_id=document.id,
                    source_field_id=source.field_id,
                    source_label=source.source_label,
                    raw_value=source.observed_value,
                    value_type=source.value_type,
                    confidence=source.observed_confidence,
                    page_number=source.page_number,
                    missing_reason_code=source.reason_code,
                    missing_reason=source.safe_reason_text,
                    review_status=PayrollImportFieldReviewStatus.MISSING,
                ))
            tables = self._build_tables(
                organization_id, import_id, document.id, result,
            )
            repository.replace_fields(import_id, rows)
            repository.replace_tables(organization_id, import_id, tables)
            requires_review = (
                any(row.review_status != PayrollImportFieldReviewStatus.UNREVIEWED
                    for row in rows)
                or bool(item.reader_warnings)
                or bool(result.tables)
            )
            transition(item, PayrollImportStatus.REVIEW_REQUIRED
                       if requires_review else PayrollImportStatus.EXTRACTED)
            item.processed_at = datetime.now(timezone.utc)
            item.last_error_code = None
            item.last_error_message = None
            sync_session.flush()
            return self._detail(item, document)
        return await self._session.run_sync(work)

    def _build_tables(
        self,
        organization_id: UUID,
        import_id: UUID,
        document_id: UUID,
        result: ExtractionResultV1,
    ) -> list[PayrollImportTable]:
        if len(result.tables) > self._settings.payroll_import_max_tables:
            raise GeneralReaderContractInvalidError()
        valid_pages = {page.page_number for page in result.pages}
        tables: list[PayrollImportTable] = []
        for table_index, source in enumerate(result.tables):
            if (
                len(source.rows) > self._settings.payroll_import_max_rows_per_table
                or len(source.columns) > self._settings.payroll_import_max_columns_per_table
                or sum(len(row.cells) for row in source.rows)
                > self._settings.payroll_import_max_cells_per_table
            ):
                raise GeneralReaderContractInvalidError()
            if (
                len(source.table_id) > 200
                or len(source.source_label) > 500
                or len(source.page_numbers) != len(set(source.page_numbers))
                or any(page not in valid_pages for page in source.page_numbers)
            ):
                raise GeneralReaderContractInvalidError()

            column_positions: dict[str, int] = {}
            source_columns: list[dict[str, object]] = []
            for column_index, column in enumerate(source.columns):
                if (
                    column.column_id in column_positions
                    or len(column.column_id) > 200
                    or len(column.source_label) > 500
                    or len(column.value_type) > 50
                ):
                    raise GeneralReaderContractInvalidError()
                column_positions[column.column_id] = column_index
                source_columns.append({
                    "column_index": column_index,
                    "source_column_id": column.column_id,
                    "source_label": column.source_label,
                    "value_type": column.value_type,
                })

            table = PayrollImportTable(
                organization_id=organization_id,
                payroll_import_id=import_id,
                payroll_import_document_id=document_id,
                source_table_index=table_index,
                source_table_id=source.table_id,
                source_label=source.source_label,
                page_numbers=list(source.page_numbers),
                source_columns=source_columns,
                warnings=list(source.warnings),
                row_count=len(source.rows),
                column_count=len(source.columns),
            )
            seen_rows: set[int] = set()
            for source_row in source.rows:
                if (
                    source_row.row_index in seen_rows
                    or source_row.page_number not in valid_pages
                    or source_row.page_number not in source.page_numbers
                    or len(source_row.coordinate_space) > 50
                    or len(source_row.extraction_source) > 50
                ):
                    raise GeneralReaderContractInvalidError()
                seen_rows.add(source_row.row_index)
                row = PayrollImportTableRow(
                    organization_id=organization_id,
                    row_index=source_row.row_index,
                    page_number=source_row.page_number,
                    bbox=self._bbox(source_row.bbox),
                    coordinate_space=source_row.coordinate_space,
                    extraction_source=source_row.extraction_source,
                )
                table.rows.append(row)
                seen_columns: set[str] = set()
                for source_cell in source_row.cells:
                    column_index = column_positions.get(source_cell.column_id)
                    if (
                        column_index is None
                        or source_cell.column_id in seen_columns
                        or len(source_cell.source_label) > 500
                        or len(source_cell.value_type) > 50
                        or len(source_cell.coordinate_space) > 50
                        or len(source_cell.extraction_source) > 50
                        or (
                            source_cell.raw_value is not None
                            and len(source_cell.raw_value)
                            > self._settings.payroll_import_max_cell_value_chars
                        )
                    ):
                        raise GeneralReaderContractInvalidError()
                    seen_columns.add(source_cell.column_id)
                    row.cells.append(PayrollImportTableCell(
                        organization_id=organization_id,
                        column_index=column_index,
                        source_column_id=source_cell.column_id,
                        column_label=source_cell.source_label,
                        raw_value=source_cell.raw_value,
                        value_type=source_cell.value_type,
                        confidence=source_cell.confidence,
                        bbox=self._bbox(source_cell.bbox),
                        coordinate_space=source_cell.coordinate_space,
                        extraction_source=source_cell.extraction_source,
                    ))
            table.source_checksum = self._table_checksum(table_index, source)
            tables.append(table)
        return tables

    @staticmethod
    def _bbox(value: list[Decimal] | None) -> list[str] | None:
        return [str(part) for part in value] if value is not None else None

    @classmethod
    def _table_checksum(cls, table_index: int, source: TableV1) -> str:
        column_positions = {
            column.column_id: index for index, column in enumerate(source.columns)
        }
        payload = {
            "source_table_index": table_index,
            "source_table_id": source.table_id,
            "source_label": source.source_label,
            "page_numbers": source.page_numbers,
            "columns": [
                {
                    "column_index": index,
                    "source_column_id": column.column_id,
                    "source_label": column.source_label,
                    "value_type": column.value_type,
                }
                for index, column in enumerate(source.columns)
            ],
            "warnings": source.warnings,
            "rows": [
                {
                    "row_index": row.row_index,
                    "page_number": row.page_number,
                    "bbox": cls._bbox(row.bbox),
                    "coordinate_space": row.coordinate_space,
                    "extraction_source": row.extraction_source,
                    "cells": [
                        {
                            "column_index": column_positions[cell.column_id],
                            "source_column_id": cell.column_id,
                            "column_label": cell.source_label,
                            "raw_value": cell.raw_value,
                            "value_type": cell.value_type,
                            "confidence": (
                                str(cell.confidence)
                                if cell.confidence is not None else None
                            ),
                            "bbox": cls._bbox(cell.bbox),
                            "coordinate_space": cell.coordinate_space,
                            "extraction_source": cell.extraction_source,
                        }
                        for cell in sorted(
                            row.cells,
                            key=lambda value: column_positions[value.column_id],
                        )
                    ],
                }
                for row in sorted(source.rows, key=lambda value: value.row_index)
            ],
        }
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    async def _mark_failed(self, organization_id: UUID, import_id: UUID,
                           error: BordroError) -> None:
        def work(sync_session: Session) -> None:
            item = PayrollImportRepository(sync_session).get_for_update(
                organization_id, import_id
            )
            if item is None or item.status != PayrollImportStatus.PROCESSING:
                return
            transition(item, PayrollImportStatus.FAILED)
            item.processed_at = datetime.now(timezone.utc)
            item.last_error_code = error.code or "IMPORT_PROCESSING_FAILED"
            item.last_error_message = error.default_message
            sync_session.flush()
        await self._session.run_sync(work)
        await self._session.commit()

    @staticmethod
    def _review_status(source: FieldV1, missing: bool) -> PayrollImportFieldReviewStatus:
        if missing or source.status == "MISSING":
            return PayrollImportFieldReviewStatus.MISSING
        if (source.status == "LOW_CONFIDENCE" or source.warnings
                or "llm" in source.extraction_source.casefold()):
            return PayrollImportFieldReviewStatus.REVIEW_REQUIRED
        return PayrollImportFieldReviewStatus.UNREVIEWED

    @staticmethod
    def _source_document(item: PayrollImport | None) -> PayrollImportDocument:
        if item is None or len(item.documents) != 1:
            raise GeneralReaderContractInvalidError("The import document metadata is invalid")
        return item.documents[0]

    @staticmethod
    def _detail(item: PayrollImport,
                document: PayrollImportDocument) -> PayrollImportRead:
        return PayrollImportRead(
            id=item.id, status=item.status, source_type=item.source_type,
            reader_provider=item.reader_provider, content_sha256=item.content_sha256,
            detected_employee_id=item.detected_employee_id,
            detected_year=item.detected_year, detected_month=item.detected_month,
            template_external_id=item.template_external_id,
            template_version=item.template_version, template_scope=item.template_scope,
            template_match_score=item.template_match_score,
            extraction_schema_version=item.extraction_schema_version,
            reader_table_count=item.reader_table_count,
            reader_warning_codes=[str(value.get("code", "READER_WARNING"))
                                  for value in item.reader_warnings],
            processing_attempt=item.processing_attempt,
            processing_started_at=item.processing_started_at,
            processed_at=item.processed_at,
            last_error_code=item.last_error_code,
            last_error_message=item.last_error_message,
            created_at=item.created_at, updated_at=item.updated_at,
            document=PayrollImportDocumentRead.model_validate(document),
        )


__all__ = ["PayrollImportService"]
