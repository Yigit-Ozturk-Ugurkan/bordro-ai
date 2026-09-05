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
    PayrollImportList,
    PayrollImportRead,
)
from app.services.auth.authentication import AuthenticatedUser
from app.services.imports.payroll_import_service import PayrollImportService
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
