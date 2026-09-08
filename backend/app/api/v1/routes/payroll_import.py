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
    PayrollImportTableList,
    PayrollImportTableRead,
    PayrollReviewCorrectionRequest,
    PayrollReviewFinalizeRequest,
    PayrollReviewRevertRequest,
    PayrollReviewSnapshotList,
    PayrollReviewSnapshotRead,
)
from app.schemas.payroll_validation import (
    PayrollValidationRunList,
    PayrollValidationRunRead,
)
from app.schemas.payroll_approval import (
    PayrollApprovalHistoryRead,
    PayrollApprovalStateRead,
    PayrollApproveRequest,
    PayrollRejectRequest,
    PayrollWarningAcknowledgementRequest,
)
from app.schemas.payroll_materialization import (
    PayrollMaterializationRead,
    PayrollMaterializationStateRead,
    PayrollMaterializeRequest,
)
from app.schemas.payroll_tax_sync import (
    PayrollTaxSyncRead,
    PayrollTaxSyncRequest,
    PayrollTaxSyncStateRead,
)
from app.schemas.payroll_tax_rebuild import (
    PayrollTaxRebuildCreateRequest,
    PayrollTaxRebuildExecuteRequest,
    PayrollTaxRebuildList,
    PayrollTaxRebuildRead,
)
from app.schemas.payroll_detail_mapping import (
    PayrollDetailCorrectionRead,
    PayrollDetailCorrectionRequest,
    PayrollDetailFinalizeRequest,
    PayrollDetailMaterializationRead,
    PayrollDetailReviewRead,
    PayrollDetailSnapshotRead,
    PayrollMappedDetailList,
)
from app.services.auth.authentication import AuthenticatedUser
from app.services.imports.payroll_import_service import PayrollImportService
from app.services.imports.payroll_adapter_service import PayrollAdapterService
from app.services.imports.payroll_review_service import PayrollReviewService
from app.services.imports.payroll_validation_service import PayrollValidationService
from app.services.imports.payroll_approval_service import PayrollApprovalService
from app.services.imports.payroll_materialization_service import (
    PayrollMaterializationService,
)
from app.services.taxation.payroll_tax_sync_service import (
    PayrollTaxLedgerSyncService,
)
from app.services.taxation.payroll_tax_rebuild_service import (
    PayrollTaxLedgerRebuildService,
)
from app.services.imports.payroll_detail_mapping_service import PayrollDetailMappingService
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
APPROVAL_WRITE_ROLES = (UserRoleType.PAYROLL_ADMIN,)


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


@router.get("/{import_id}/tables", response_model=PayrollImportTableList)
async def get_payroll_import_tables(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
    storage: DocumentStorage = Depends(get_document_storage),
    reader: GeneralReaderClient = Depends(get_general_reader_client),
) -> PayrollImportTableList:
    return await service(session, storage, reader).tables(user, import_id)


@router.get(
    "/{import_id}/tables/{table_id}", response_model=PayrollImportTableRead,
)
async def get_payroll_import_table(
    import_id: UUID,
    table_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
    storage: DocumentStorage = Depends(get_document_storage),
    reader: GeneralReaderClient = Depends(get_general_reader_client),
) -> PayrollImportTableRead:
    return await service(session, storage, reader).table(user, import_id, table_id)


@router.post("/{import_id}/detail-mapping", response_model=PayrollMappedDetailList)
async def map_payroll_import_details(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*APPROVAL_WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollMappedDetailList:
    return await PayrollDetailMappingService(session).run(user, import_id)


@router.get("/{import_id}/mapped-details", response_model=PayrollMappedDetailList)
async def get_payroll_import_mapped_details(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollMappedDetailList:
    return await PayrollDetailMappingService(session).mapped(user, import_id)


@router.get("/{import_id}/detail-review", response_model=PayrollDetailReviewRead)
async def get_payroll_import_detail_review(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollDetailReviewRead:
    return await PayrollDetailMappingService(session).review(user, import_id)


@router.post(
    "/{import_id}/detail-review/rows/{mapped_detail_id}",
    response_model=PayrollDetailCorrectionRead,
)
async def correct_payroll_import_detail(
    import_id: UUID,
    mapped_detail_id: UUID,
    request: PayrollDetailCorrectionRequest,
    user: AuthenticatedUser = Depends(require_roles(*WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollDetailCorrectionRead:
    return await PayrollDetailMappingService(session).correct(
        user, import_id, mapped_detail_id, request,
    )


@router.post(
    "/{import_id}/detail-review/finalize", response_model=PayrollDetailSnapshotRead,
)
async def finalize_payroll_import_detail_review(
    import_id: UUID,
    request: PayrollDetailFinalizeRequest,
    user: AuthenticatedUser = Depends(require_roles(*WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollDetailSnapshotRead:
    return await PayrollDetailMappingService(session).finalize(
        user, import_id, request.expected_row_version,
    )


@router.get(
    "/{import_id}/detail-snapshots/{snapshot_id}",
    response_model=PayrollDetailSnapshotRead,
)
async def get_payroll_import_detail_snapshot(
    import_id: UUID,
    snapshot_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollDetailSnapshotRead:
    return await PayrollDetailMappingService(session).snapshot(
        user, import_id, snapshot_id,
    )


@router.post(
    "/{import_id}/materialization/details",
    response_model=PayrollDetailMaterializationRead,
)
async def materialize_payroll_import_details(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*APPROVAL_WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollDetailMaterializationRead:
    return await PayrollDetailMappingService(session).materialize(user, import_id)


@router.get(
    "/{import_id}/materialization/details",
    response_model=PayrollDetailMaterializationRead,
)
async def get_materialized_payroll_import_details(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollDetailMaterializationRead:
    return await PayrollDetailMappingService(session).materialized(user, import_id)


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


@router.post(
    "/{import_id}/review/snapshots/{snapshot_id}/validate",
    response_model=PayrollValidationRunRead,
)
async def validate_payroll_import_review_snapshot(
    import_id: UUID,
    snapshot_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollValidationRunRead:
    return await PayrollValidationService(session).validate_snapshot(
        user, import_id, snapshot_id,
    )


@router.get(
    "/{import_id}/validations", response_model=PayrollValidationRunList,
)
async def list_payroll_import_validations(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollValidationRunList:
    return await PayrollValidationService(session).list(user, import_id)


@router.get(
    "/{import_id}/validations/{run_id}", response_model=PayrollValidationRunRead,
)
async def get_payroll_import_validation(
    import_id: UUID,
    run_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollValidationRunRead:
    return await PayrollValidationService(session).get(user, import_id, run_id)


@router.get("/{import_id}/approval", response_model=PayrollApprovalStateRead)
async def get_current_payroll_import_approval(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollApprovalStateRead:
    return await PayrollApprovalService(session).current(user, import_id)


@router.get("/{import_id}/approvals", response_model=PayrollApprovalHistoryRead)
async def list_payroll_import_approvals(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollApprovalHistoryRead:
    return await PayrollApprovalService(session).history(user, import_id)


@router.post(
    "/{import_id}/validations/{run_id}/warnings/{result_id}/acknowledge",
    response_model=PayrollApprovalStateRead,
)
async def acknowledge_payroll_import_validation_warning(
    import_id: UUID,
    run_id: UUID,
    result_id: UUID,
    request: PayrollWarningAcknowledgementRequest,
    user: AuthenticatedUser = Depends(require_roles(*APPROVAL_WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollApprovalStateRead:
    return await PayrollApprovalService(session).acknowledge_warning(
        user, import_id, run_id, result_id, request.note,
    )


@router.post(
    "/{import_id}/validations/{run_id}/approve",
    response_model=PayrollApprovalStateRead,
)
async def approve_payroll_import_validation(
    import_id: UUID,
    run_id: UUID,
    request: PayrollApproveRequest,
    user: AuthenticatedUser = Depends(require_roles(*APPROVAL_WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollApprovalStateRead:
    return await PayrollApprovalService(session).approve(
        user, import_id, run_id, request.note,
    )


@router.post(
    "/{import_id}/validations/{run_id}/reject",
    response_model=PayrollApprovalStateRead,
)
async def reject_payroll_import_validation(
    import_id: UUID,
    run_id: UUID,
    request: PayrollRejectRequest,
    user: AuthenticatedUser = Depends(require_roles(*APPROVAL_WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollApprovalStateRead:
    return await PayrollApprovalService(session).reject(
        user, import_id, run_id, request.reason,
    )


@router.post(
    "/{import_id}/approvals/{approval_id}/materialize",
    response_model=PayrollMaterializationRead,
)
async def materialize_payroll_import_approval(
    import_id: UUID,
    approval_id: UUID,
    request: PayrollMaterializeRequest,
    user: AuthenticatedUser = Depends(require_roles(*APPROVAL_WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollMaterializationRead:
    del request
    return await PayrollMaterializationService(session).materialize(
        user, import_id, approval_id,
    )


@router.get(
    "/{import_id}/materialization",
    response_model=PayrollMaterializationStateRead,
)
async def get_current_payroll_import_materialization(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollMaterializationStateRead:
    return await PayrollMaterializationService(session).current(user, import_id)


@router.post(
    "/{import_id}/materialization/tax-sync",
    response_model=PayrollTaxSyncRead,
)
async def synchronize_payroll_import_tax_ledger(
    import_id: UUID,
    request: PayrollTaxSyncRequest,
    user: AuthenticatedUser = Depends(require_roles(*APPROVAL_WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollTaxSyncRead:
    del request
    return await PayrollTaxLedgerSyncService(session).sync(user, import_id)


@router.get(
    "/{import_id}/materialization/tax-sync",
    response_model=PayrollTaxSyncStateRead,
)
async def get_payroll_import_tax_ledger_sync(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollTaxSyncStateRead:
    return await PayrollTaxLedgerSyncService(session).current(user, import_id)


@router.post(
    "/{import_id}/materialization/tax-rebuilds",
    response_model=PayrollTaxRebuildRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_payroll_tax_ledger_rebuild(
    import_id: UUID,
    request: PayrollTaxRebuildCreateRequest,
    user: AuthenticatedUser = Depends(require_roles(*APPROVAL_WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollTaxRebuildRead:
    del request
    return await PayrollTaxLedgerRebuildService(session).create(user, import_id)


@router.get(
    "/{import_id}/materialization/tax-rebuilds",
    response_model=PayrollTaxRebuildList,
)
async def list_payroll_tax_ledger_rebuilds(
    import_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollTaxRebuildList:
    return await PayrollTaxLedgerRebuildService(session).list(user, import_id)


@router.get(
    "/{import_id}/materialization/tax-rebuilds/{rebuild_id}",
    response_model=PayrollTaxRebuildRead,
)
async def get_payroll_tax_ledger_rebuild(
    import_id: UUID,
    rebuild_id: UUID,
    user: AuthenticatedUser = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollTaxRebuildRead:
    return await PayrollTaxLedgerRebuildService(session).get(
        user, import_id, rebuild_id,
    )


@router.post(
    "/{import_id}/materialization/tax-rebuilds/{rebuild_id}/execute",
    response_model=PayrollTaxRebuildRead,
)
async def execute_payroll_tax_ledger_rebuild(
    import_id: UUID,
    rebuild_id: UUID,
    request: PayrollTaxRebuildExecuteRequest,
    user: AuthenticatedUser = Depends(require_roles(*APPROVAL_WRITE_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PayrollTaxRebuildRead:
    del request
    return await PayrollTaxLedgerRebuildService(session).execute(
        user, import_id, rebuild_id,
    )
