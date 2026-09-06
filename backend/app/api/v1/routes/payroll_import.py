"""Authenticated, organization-scoped payroll document ingestion endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth_dependencies import require_roles
from app.api.v1.dependencies import get_document_storage, get_general_reader_client
from app.db.session import get_db
from app.integrations.general_reader.client import GeneralReaderClient
from app.models.enums import UserRoleType
from app.schemas.payroll_import import (
    PayrollImportFieldList,
    PayrollImportReviewRead,
    PayrollImportMappedFieldList,
    PayrollImportMappingSummary,
    PayrollImportList,
    PayrollImportRead,
    PayrollReviewCorrectionRequest,
    PayrollReviewFinalizeRequest,
    PayrollReviewRevertRequest,
    PayrollReviewSnapshotList,
    PayrollReviewSnapshotRead,
)
from app.services.auth.authentication import AuthenticatedUser
from app.services.imports.payroll_import_service import PayrollImportService
from app.services.imports.payroll_adapter_service import PayrollAdapterService
from app.services.imports.payroll_review_service import PayrollReviewService
from app.storage.document_storage import DocumentStorage

router = APIRouter(prefix="/api/v1/payroll-imports", tags=["payroll-imports"])

READ_ROLES = (
    UserRoleType.PAYROLL_ADMIN,
    UserRoleType.HR_ADMIN,
    UserRoleType.AUDITOR,
)
WRITE_ROLES = (
    UserRoleType.PAYROLL_ADMIN,
    UserRoleType.HR_ADMIN,
)


def service(session: AsyncSession, storage: DocumentStorage,
            reader: GeneralReaderClient) -> PayrollImportService:
    return PayrollImportService(session, storage, reader)


@router.post("", response_model=PayrollImportRead,
             status_code=status.HTTP_201_CREATED)
async def upload_payroll_import(
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(require_roles(*WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
    storage: DocumentStorage = Depends(get_document_storage),
    reader: GeneralReaderClient = Depends(get_general_reader_client),
) -> PayrollImportRead:
    try:
        return await service(session, storage, reader).create(user, file)
    finally:
        await file.close()


@router.get("", response_model=PayrollImportList)
async def list_payroll_imports(
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
    storage: DocumentStorage = Depends(get_document_storage),
    reader: GeneralReaderClient = Depends(get_general_reader_client),
) -> PayrollImportList:
    return await service(session, storage, reader).list(user)


@router.get("/{import_id}", response_model=PayrollImportRead)
async def get_payroll_import(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
    storage: DocumentStorage = Depends(get_document_storage),
    reader: GeneralReaderClient = Depends(get_general_reader_client),
) -> PayrollImportRead:
    return await service(session, storage, reader).get(user, import_id)


@router.get("/{import_id}/fields", response_model=PayrollImportFieldList)
async def get_payroll_import_fields(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
    storage: DocumentStorage = Depends(get_document_storage),
    reader: GeneralReaderClient = Depends(get_general_reader_client),
) -> PayrollImportFieldList:
    return await service(session, storage, reader).fields(user, import_id)


@router.post("/{import_id}/process", response_model=PayrollImportRead)
async def process_payroll_import(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
    storage: DocumentStorage = Depends(get_document_storage),
    reader: GeneralReaderClient = Depends(get_general_reader_client),
) -> PayrollImportRead:
    return await service(session, storage, reader).process(user, import_id)


@router.post("/{import_id}/map", response_model=PayrollImportMappingSummary)
async def map_payroll_import(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollImportMappingSummary:
    return await PayrollAdapterService(session).run(user, import_id)


@router.get("/{import_id}/mapped-fields", response_model=PayrollImportMappedFieldList)
async def get_payroll_import_mapped_fields(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollImportMappedFieldList:
    return await PayrollAdapterService(session).mapped_fields(user, import_id)


@router.get("/{import_id}/mapping-summary", response_model=PayrollImportMappingSummary)
async def get_payroll_import_mapping_summary(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollImportMappingSummary:
    return await PayrollAdapterService(session).summary(user, import_id)


@router.post("/{import_id}/review", response_model=PayrollImportReviewRead)
async def start_payroll_import_review(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollImportReviewRead:
    return await PayrollReviewService(session).start(user, import_id)


@router.get("/{import_id}/review", response_model=PayrollImportReviewRead)
async def get_payroll_import_review(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollImportReviewRead:
    return await PayrollReviewService(session).get(user, import_id)


@router.post(
    "/{import_id}/review/fields/{mapped_field_id}",
    response_model=PayrollImportReviewRead,
)
async def correct_payroll_import_review_field(
    import_id: UUID,
    mapped_field_id: UUID,
    request: PayrollReviewCorrectionRequest,
    user: AuthenticatedUser = Depends(require_roles(*WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollImportReviewRead:
    return await PayrollReviewService(session).correct(
        user, import_id, mapped_field_id, request,
    )


@router.post(
    "/{import_id}/review/fields/{mapped_field_id}/revert",
    response_model=PayrollImportReviewRead,
)
async def revert_payroll_import_review_field(
    import_id: UUID,
    mapped_field_id: UUID,
    request: PayrollReviewRevertRequest,
    user: AuthenticatedUser = Depends(require_roles(*WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollImportReviewRead:
    return await PayrollReviewService(session).revert(
        user, import_id, mapped_field_id, request,
    )


@router.post(
    "/{import_id}/review/finalize", response_model=PayrollReviewSnapshotRead,
)
async def finalize_payroll_import_review(
    import_id: UUID,
    request: PayrollReviewFinalizeRequest,
    user: AuthenticatedUser = Depends(require_roles(*WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollReviewSnapshotRead:
    return await PayrollReviewService(session).finalize(user, import_id, request)


@router.get(
    "/{import_id}/review/snapshots", response_model=PayrollReviewSnapshotList,
)
async def list_payroll_import_review_snapshots(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollReviewSnapshotList:
    return await PayrollReviewService(session).snapshots(user, import_id)


@router.get(
    "/{import_id}/review/snapshots/{snapshot_id}",
    response_model=PayrollReviewSnapshotRead,
)
async def get_payroll_import_review_snapshot(
    import_id: UUID,
    snapshot_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollReviewSnapshotRead:
    return await PayrollReviewService(session).snapshot(user, import_id, snapshot_id)
