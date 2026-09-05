"""Durable V2.1A upload and explicit extraction orchestration."""

from __future__ import annotations

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
)
from app.integrations.general_reader.client import GeneralReaderClient
from app.integrations.general_reader.schemas import ExtractionResultV1, FieldV1
from app.models.enums import PayrollImportFieldReviewStatus, PayrollImportStatus
from app.models.payroll_import import (
    PayrollImport,
    PayrollImportDocument,
    PayrollImportField,
)
from app.repositories.payroll_import_repository import PayrollImportRepository
from app.schemas.payroll_import import (
    PayrollImportDocumentRead,
    PayrollImportFieldList,
    PayrollImportList,
    PayrollImportListItem,
    PayrollImportRead,
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
            if result.tables:
                item.reader_warnings.append({
                    "code": "TABLE_STAGING_DEFERRED", "count": len(result.tables)
                })
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
            repository.replace_fields(import_id, rows)
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
